from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import html
import json
import os
import secrets
import time
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import asyncpg
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

_POOL: asyncpg.Pool | None = None
_POOL_LOCK = asyncio.Lock()
_SCHEMA_READY = False
_SCHEMA_LOCK = asyncio.Lock()
SCOPES = "mcp:invoke"


def _origin() -> str:
    configured = os.environ.get("HANDU_MCP_PUBLIC_ORIGIN", "").strip().rstrip("/")
    if configured:
        parsed = urlparse(configured)
        if parsed.scheme != "https" or not parsed.netloc:
            raise RuntimeError("HANDU_MCP_PUBLIC_ORIGIN must be an HTTPS origin")
        return f"{parsed.scheme}://{parsed.netloc}"
    raise RuntimeError("HANDU_MCP_PUBLIC_ORIGIN is not configured")


def _resource() -> str:
    return _origin() + "/mcp"


def _dsn() -> str:
    value = os.environ.get("DTK_DATABASE_URL", "").strip()
    if not value:
        raise RuntimeError("DTK_DATABASE_URL is not configured")
    return value.replace("postgresql+asyncpg://", "postgresql://", 1)


async def _pool() -> asyncpg.Pool:
    global _POOL
    if _POOL is None:
        async with _POOL_LOCK:
            if _POOL is None:
                _POOL = await asyncpg.create_pool(_dsn(), min_size=1, max_size=4, command_timeout=10)
    return _POOL


async def _ensure_schema() -> asyncpg.Pool:
    global _SCHEMA_READY
    pool = await _pool()
    if _SCHEMA_READY:
        return pool
    async with _SCHEMA_LOCK:
        if not _SCHEMA_READY:
            async with pool.acquire() as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS handu_oauth_clients (
                        issuer TEXT NOT NULL,
                        client_id TEXT NOT NULL,
                        client_name TEXT NOT NULL,
                        redirect_uris JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (issuer, client_id)
                    );
                    CREATE TABLE IF NOT EXISTS handu_oauth_transactions (
                        tx_hash TEXT PRIMARY KEY,
                        issuer TEXT NOT NULL,
                        client_id TEXT NOT NULL,
                        redirect_uri TEXT NOT NULL,
                        code_challenge TEXT NOT NULL,
                        oauth_state TEXT NOT NULL,
                        resource TEXT NOT NULL,
                        scope TEXT NOT NULL,
                        expires_at TIMESTAMPTZ NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS handu_oauth_codes (
                        code_hash TEXT PRIMARY KEY,
                        issuer TEXT NOT NULL,
                        client_id TEXT NOT NULL,
                        redirect_uri TEXT NOT NULL,
                        code_challenge TEXT NOT NULL,
                        resource TEXT NOT NULL,
                        scope TEXT NOT NULL,
                        expires_at TIMESTAMPTZ NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS handu_oauth_access (
                        token_hash TEXT PRIMARY KEY,
                        issuer TEXT NOT NULL,
                        client_id TEXT NOT NULL,
                        resource TEXT NOT NULL,
                        scope TEXT NOT NULL,
                        expires_at TIMESTAMPTZ NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS handu_oauth_refresh (
                        token_hash TEXT PRIMARY KEY,
                        issuer TEXT NOT NULL,
                        client_id TEXT NOT NULL,
                        resource TEXT NOT NULL,
                        scope TEXT NOT NULL,
                        expires_at TIMESTAMPTZ NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS handu_oauth_login_attempts (
                        ip_hash TEXT PRIMARY KEY,
                        failures INTEGER NOT NULL,
                        window_start TIMESTAMPTZ NOT NULL
                    );
                """)
            _SCHEMA_READY = True
    return pool


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _random_token() -> str:
    return secrets.token_urlsafe(32)


def _constant_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def _json(data: dict, status_code: int = 200, headers: dict[str, str] | None = None) -> JSONResponse:
    result_headers = {"Cache-Control": "no-store", "Pragma": "no-cache"}
    if headers:
        result_headers.update(headers)
    return JSONResponse(data, status_code=status_code, headers=result_headers)


def _oauth_error(error: str, description: str, status_code: int = 400) -> JSONResponse:
    return _json({"error": error, "error_description": description}, status_code)


def _metadata() -> dict:
    base = _origin()
    return {
        "issuer": base,
        "authorization_endpoint": base + "/authorize",
        "token_endpoint": base + "/token",
        "registration_endpoint": base + "/register",
        "response_types_supported": ["code"],
        "response_modes_supported": ["query"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": [SCOPES, "offline_access"],
    }


def _protected_metadata() -> dict:
    return {
        "resource": _resource(),
        "authorization_servers": [_origin()],
        "bearer_methods_supported": ["header"],
        "scopes_supported": [SCOPES],
    }


def _valid_redirect(value: str) -> bool:
    try:
        parsed = urlparse(value)
        return (
            parsed.scheme == "https"
            and parsed.hostname == "chatgpt.com"
            and parsed.username is None
            and parsed.password is None
            and parsed.fragment == ""
            and (
                parsed.path == "/connector_platform_oauth_redirect"
                or parsed.path.startswith("/connector/oauth/")
            )
        )
    except Exception:
        return False


def _canonical_resource(value: str | None) -> str | None:
    expected = _resource()
    if value in (None, "", _origin(), expected):
        return expected
    return None


def _form(body: bytes) -> dict[str, str]:
    values = parse_qs(body.decode("utf-8", "strict"), keep_blank_values=True, max_num_fields=32)
    return {key: entries[0] for key, entries in values.items() if entries}


def _page(body: str, status_code: int = 200) -> HTMLResponse:
    headers = {
        "Cache-Control": "no-store",
        "Pragma": "no-cache",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
    }
    return HTMLResponse(
        "<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>HANDU MCP</title></head><body>" + body + "</body></html>",
        status_code=status_code,
        headers=headers,
    )


def _chatgpt_callback(redirect_uri: str, code: str, state: str) -> str:
    parsed = urlparse(redirect_uri)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query["code"] = [code]
    query["state"] = [state]
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(query, doseq=True), ""))


async def valid_oauth_access_token(token: str, expected_resource: str) -> bool:
    try:
        pool = await _ensure_schema()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT 1 FROM handu_oauth_access WHERE token_hash=$1 AND issuer=$2 AND resource=$3 AND expires_at>NOW()",
                _digest(token), _origin(), expected_resource,
            )
        return row is not None
    except Exception:
        return False


def install_oauth_routes(mcp, service_label: str) -> None:
    @mcp.custom_route("/.well-known/oauth-authorization-server", methods=["GET"])
    async def authorization_server_metadata(_: Request) -> Response:
        return _json(_metadata())

    @mcp.custom_route("/.well-known/openid-configuration", methods=["GET"])
    async def openid_configuration(_: Request) -> Response:
        return _json(_metadata())

    @mcp.custom_route("/.well-known/oauth-protected-resource", methods=["GET"])
    async def protected_resource_metadata(_: Request) -> Response:
        return _json(_protected_metadata())

    @mcp.custom_route("/.well-known/oauth-protected-resource/mcp", methods=["GET"])
    async def protected_resource_path_metadata(_: Request) -> Response:
        return _json(_protected_metadata())

    @mcp.custom_route("/mcp/.well-known/oauth-protected-resource", methods=["GET"])
    async def protected_resource_nested_metadata(_: Request) -> Response:
        return _json(_protected_metadata())

    @mcp.custom_route("/register", methods=["POST"])
    async def register(request: Request) -> Response:
        try:
            body = await request.body()
            if len(body) > 65536:
                return _oauth_error("invalid_client_metadata", "Registration request is too large.")
            metadata = json.loads(body)
            redirects = metadata.get("redirect_uris")
            if not isinstance(redirects, list) or not redirects or len(redirects) > 10:
                return _oauth_error("invalid_redirect_uri", "ChatGPT redirect_uris are required.")
            redirects = [str(item) for item in redirects]
            if any(not _valid_redirect(item) for item in redirects):
                return _oauth_error("invalid_redirect_uri", "Only ChatGPT OAuth callbacks are accepted.")
            client_id = _random_token()
            client_name = str(metadata.get("client_name") or metadata.get("application_name") or "ChatGPT")[:100]
            pool = await _ensure_schema()
            await pool.execute(
                "INSERT INTO handu_oauth_clients (issuer,client_id,client_name,redirect_uris) VALUES ($1,$2,$3,$4::jsonb)",
                _origin(), client_id, client_name, json.dumps(redirects),
            )
            return _json({
                "client_id": client_id,
                "client_id_issued_at": int(time.time()),
                "client_name": client_name,
                "redirect_uris": redirects,
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
            }, 201)
        except Exception:
            return _oauth_error("invalid_client_metadata", "Could not register the ChatGPT client.")

    @mcp.custom_route("/authorize", methods=["GET"])
    async def authorize(request: Request) -> Response:
        try:
            q = request.query_params
            client_id = q.get("client_id", "")[:200]
            redirect_uri = q.get("redirect_uri", "")[:1000]
            state = q.get("state", "")[:1000]
            challenge = q.get("code_challenge", "")[:200]
            resource = _canonical_resource(q.get("resource"))
            if q.get("response_type") != "code" or q.get("code_challenge_method") != "S256" or not challenge or not state or not resource:
                return _oauth_error("invalid_request", "OAuth authorization request is incomplete or unsupported.")
            if not _valid_redirect(redirect_uri):
                return _oauth_error("invalid_redirect_uri", "Only ChatGPT OAuth callbacks are accepted.")
            pool = await _ensure_schema()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT client_name,redirect_uris FROM handu_oauth_clients WHERE issuer=$1 AND client_id=$2",
                    _origin(), client_id,
                )
            redirects = row["redirect_uris"] if row else []
            if isinstance(redirects, str):
                redirects = json.loads(redirects)
            if not row or redirect_uri not in redirects:
                return _oauth_error("invalid_client", "ChatGPT client is not registered.")
            requested_scopes = set(q.get("scope", SCOPES).split())
            allowed_scopes = {SCOPES, "offline_access"}
            if not requested_scopes:
                requested_scopes = {SCOPES}
            if SCOPES not in requested_scopes:
                requested_scopes.add(SCOPES)
            if not requested_scopes.issubset(allowed_scopes):
                return _oauth_error("invalid_scope", "Only MCP invocation and offline access are supported.")
            granted_scope = " ".join(sorted(requested_scopes))
            transaction = _random_token()
            await pool.execute(
                "INSERT INTO handu_oauth_transactions (tx_hash,issuer,client_id,redirect_uri,code_challenge,oauth_state,resource,scope,expires_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,NOW()+interval '10 minutes')",
                _digest(transaction), _origin(), client_id, redirect_uri, challenge, state, resource, granted_scope,
            )
            label = html.escape(str(row["client_name"]))
            service = html.escape(service_label)
            body = (
                "<main style='font:16px system-ui;max-width:440px;margin:12vh auto;padding:24px;border:1px solid #ddd;border-radius:14px'>"
                "<h2>Connect HANDU " + service + "</h2><p>Authorize <b>" + label + "</b> to use the HANDU " + service + " MCP tools.</p>"
                "<p>Sign in with the HANDU Railway test administrator credentials. Credentials are sent only to this Railway service over HTTPS.</p>"
                "<form method='post' action='/authorize/login'><input type='hidden' name='transaction' value='" + html.escape(transaction, quote=True) + "'>"
                "<label>Username<br><input name='username' autocomplete='username' required style='box-sizing:border-box;width:100%;padding:10px;margin:6px 0 14px'></label>"
                "<label>Password<br><input type='password' name='password' autocomplete='current-password' required style='box-sizing:border-box;width:100%;padding:10px;margin:6px 0 18px'></label>"
                "<button style='padding:10px 16px'>Continue</button></form></main>"
            )
            return _page(body)
        except Exception:
            return _oauth_error("server_error", "Authorization could not be started.", 500)

    @mcp.custom_route("/authorize/login", methods=["POST"])
    async def authorize_login(request: Request) -> Response:
        try:
            raw = await request.body()
            if len(raw) > 16384:
                return _page("<main><h2>Sign-in failed</h2><p>Return to ChatGPT and reconnect the app.</p></main>", 400)
            form = _form(raw)
            transaction = form.get("transaction", "")[:200]
            username = form.get("username", "")
            password = form.get("password", "")
            ip = (request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for", "unknown").split(",")[0]).strip()[:80]
            ip_hash = _digest(_origin() + "\0" + ip)
            pool = await _ensure_schema()
            async with pool.acquire() as conn:
                attempts = await conn.fetchrow("SELECT failures,window_start FROM handu_oauth_login_attempts WHERE ip_hash=$1", ip_hash)
                if attempts and attempts["window_start"].timestamp() > time.time() - 900 and attempts["failures"] >= 8:
                    return _page("<main><h2>Too many attempts</h2><p>Wait 15 minutes, then try again.</p></main>", 429)
                tx = await conn.fetchrow(
                    "SELECT * FROM handu_oauth_transactions WHERE tx_hash=$1 AND issuer=$2 AND expires_at>NOW()",
                    _digest(transaction), _origin(),
                )
            if not tx:
                return _page("<main><h2>Sign-in expired</h2><p>Return to ChatGPT and reconnect the app.</p></main>", 400)
            configured_user = os.environ.get("HANDU_DTK_ADMIN_USERNAME", "")
            configured_password = os.environ.get("HANDU_DTK_ADMIN_PASSWORD", "")
            accepted = bool(configured_user and configured_password and _constant_equal(username, configured_user) and _constant_equal(password, configured_password))
            if not accepted:
                await pool.execute(
                    "INSERT INTO handu_oauth_login_attempts (ip_hash,failures,window_start) VALUES ($1,1,NOW()) "
                    "ON CONFLICT (ip_hash) DO UPDATE SET failures=CASE WHEN handu_oauth_login_attempts.window_start<NOW()-interval '15 minutes' THEN 1 ELSE handu_oauth_login_attempts.failures+1 END, "
                    "window_start=CASE WHEN handu_oauth_login_attempts.window_start<NOW()-interval '15 minutes' THEN NOW() ELSE handu_oauth_login_attempts.window_start END",
                    ip_hash,
                )
                await pool.execute("DELETE FROM handu_oauth_transactions WHERE tx_hash=$1", _digest(transaction))
                return _page("<main><h2>Sign-in failed</h2><p>Credentials were not accepted. Return to ChatGPT and try again.</p></main>", 401)
            await pool.execute("DELETE FROM handu_oauth_login_attempts WHERE ip_hash=$1", ip_hash)
            code = _random_token()
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute("DELETE FROM handu_oauth_transactions WHERE tx_hash=$1", _digest(transaction))
                    await conn.execute(
                        "INSERT INTO handu_oauth_codes (code_hash,issuer,client_id,redirect_uri,code_challenge,resource,scope,expires_at) VALUES ($1,$2,$3,$4,$5,$6,$7,NOW()+interval '5 minutes')",
                        _digest(code), _origin(), tx["client_id"], tx["redirect_uri"], tx["code_challenge"], tx["resource"], tx["scope"],
                    )
            return RedirectResponse(_chatgpt_callback(tx["redirect_uri"], code, tx["oauth_state"]), status_code=302)
        except Exception:
            return _page("<main><h2>Sign-in failed</h2><p>Return to ChatGPT and reconnect the app.</p></main>", 500)

    @mcp.custom_route("/token", methods=["POST"])
    async def token(request: Request) -> Response:
        try:
            raw = await request.body()
            if len(raw) > 16384:
                return _oauth_error("invalid_request", "Token request is too large.")
            form = _form(raw)
            client_id = form.get("client_id", "")[:200]
            issuer = _origin()
            pool = await _ensure_schema()
            exists = await pool.fetchval("SELECT 1 FROM handu_oauth_clients WHERE issuer=$1 AND client_id=$2", issuer, client_id)
            if not exists:
                return _oauth_error("invalid_client", "Client is not registered.")
            if form.get("grant_type") == "authorization_code":
                code = form.get("code", "")
                redirect_uri = form.get("redirect_uri", "")
                verifier = form.get("code_verifier", "")
                if not 43 <= len(verifier) <= 128:
                    return _oauth_error("invalid_grant", "PKCE verification failed.")
                challenge = _b64url(hashlib.sha256(verifier.encode("ascii", "strict")).digest())
                async with pool.acquire() as conn:
                    async with conn.transaction():
                        row = await conn.fetchrow(
                            "SELECT * FROM handu_oauth_codes WHERE code_hash=$1 AND issuer=$2 AND client_id=$3 AND redirect_uri=$4 AND expires_at>NOW() FOR UPDATE",
                            _digest(code), issuer, client_id, redirect_uri,
                        )
                        if not row or not _constant_equal(row["code_challenge"], challenge):
                            return _oauth_error("invalid_grant", "Authorization code or PKCE verifier is invalid.")
                        await conn.execute("DELETE FROM handu_oauth_codes WHERE code_hash=$1", _digest(code))
                        access = _random_token()
                        refresh = _random_token()
                        await conn.execute(
                            "INSERT INTO handu_oauth_access (token_hash,issuer,client_id,resource,scope,expires_at) VALUES ($1,$2,$3,$4,$5,NOW()+interval '15 minutes')",
                            _digest(access), issuer, client_id, row["resource"], row["scope"],
                        )
                        await conn.execute(
                            "INSERT INTO handu_oauth_refresh (token_hash,issuer,client_id,resource,scope,expires_at) VALUES ($1,$2,$3,$4,$5,NOW()+interval '30 days')",
                            _digest(refresh), issuer, client_id, row["resource"], row["scope"],
                        )
                return _json({"access_token": access, "token_type": "Bearer", "expires_in": 900, "refresh_token": refresh, "scope": row["scope"], "resource": row["resource"]})
            if form.get("grant_type") == "refresh_token":
                refresh = form.get("refresh_token", "")
                async with pool.acquire() as conn:
                    async with conn.transaction():
                        row = await conn.fetchrow(
                            "SELECT * FROM handu_oauth_refresh WHERE token_hash=$1 AND issuer=$2 AND client_id=$3 AND expires_at>NOW() FOR UPDATE",
                            _digest(refresh), issuer, client_id,
                        )
                        if not row:
                            return _oauth_error("invalid_grant", "Refresh token is invalid or expired.")
                        await conn.execute("DELETE FROM handu_oauth_refresh WHERE token_hash=$1", _digest(refresh))
                        access = _random_token()
                        next_refresh = _random_token()
                        await conn.execute(
                            "INSERT INTO handu_oauth_access (token_hash,issuer,client_id,resource,scope,expires_at) VALUES ($1,$2,$3,$4,$5,NOW()+interval '15 minutes')",
                            _digest(access), issuer, client_id, row["resource"], row["scope"],
                        )
                        await conn.execute(
                            "INSERT INTO handu_oauth_refresh (token_hash,issuer,client_id,resource,scope,expires_at) VALUES ($1,$2,$3,$4,$5,NOW()+interval '30 days')",
                            _digest(next_refresh), issuer, client_id, row["resource"], row["scope"],
                        )
                return _json({"access_token": access, "token_type": "Bearer", "expires_in": 900, "refresh_token": next_refresh, "scope": row["scope"], "resource": row["resource"]})
            return _oauth_error("unsupported_grant_type", "Grant type is not supported.")
        except Exception:
            return _oauth_error("server_error", "Token exchange failed.", 500)

