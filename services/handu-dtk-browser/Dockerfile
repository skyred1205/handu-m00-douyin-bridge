FROM python:3.12.8-slim-bookworm

ARG DTK_REPO=https://github.com/Evil0ctal/Douyin_TikTok_Download_API
ARG DTK_COMMIT=31d56df1462e99f24621eb2c6f060af183bf24fd
ARG CLOAKBROWSER_REPO=https://github.com/CloakHQ/cloakbrowser
ARG CLOAKBROWSER_COMMIT=f04c23da285b3b3d3cf10c8f9d282e7adc1d52ce
ARG CLOAKBROWSER_HOME=/opt/cloakbrowser
ARG DTK_UID=10001
ARG DTK_GID=10001

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/srv \
    CLOAKBROWSER_HOME=${CLOAKBROWSER_HOME} \
    HOME=/tmp \
    XDG_CACHE_HOME=/tmp/.cache \
    DTK_BROWSER_BIND_HOST=0.0.0.0 \
    DTK_BROWSER_BIND_PORT=9000 \
    DTK_BROWSER_PROFILE_ROOT=/profiles \
    DTK_BROWSER_BACKEND=cloak \
    DTK_BROWSER_BACKEND_PIN="${CLOAKBROWSER_REPO}@${CLOAKBROWSER_COMMIT}"

RUN apt-get update && apt-get install --no-install-recommends -y \
      ca-certificates \
      fonts-liberation \
      fonts-noto-color-emoji \
      fonts-noto-cjk \
      libasound2 \
      libatk-bridge2.0-0 \
      libatk1.0-0 \
      libatspi2.0-0 \
      libcairo2 \
      libcups2 \
      libdbus-1-3 \
      libdrm2 \
      libexpat1 \
      libgbm1 \
      libglib2.0-0 \
      libnspr4 \
      libnss3 \
      libpango-1.0-0 \
      libx11-6 \
      libxcb1 \
      libxcomposite1 \
      libxdamage1 \
      libxext6 \
      libxfixes3 \
      libxkbcommon0 \
      libxrandr2 \
      xdg-utils \
      git \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --filter=blob:none "${DTK_REPO}" /tmp/dtk \
    && cd /tmp/dtk \
    && git checkout --detach "${DTK_COMMIT}" \
    && test "$(git rev-parse HEAD)" = "${DTK_COMMIT}"

WORKDIR /srv
RUN pip install --no-cache-dir -r /tmp/dtk/docker/browser_rpc/requirements.txt
RUN pip install --no-cache-dir "cloakbrowser @ git+${CLOAKBROWSER_REPO}@${CLOAKBROWSER_COMMIT}" \
    && mkdir -p "${CLOAKBROWSER_HOME}" \
    && HOME="${CLOAKBROWSER_HOME}" python -m cloakbrowser install \
    && HOME="${CLOAKBROWSER_HOME}" python -m cloakbrowser info | grep -qE "^Installed: *True" \
    && chmod -R a+rX "${CLOAKBROWSER_HOME}"

RUN cp -R /tmp/dtk/docker/browser_rpc /srv/browser_rpc \
    && cp /tmp/dtk/docker/browser-entrypoint.sh /usr/local/bin/browser-entrypoint \
    && chmod 0555 /usr/local/bin/browser-entrypoint \
    && rm -rf /tmp/dtk \
    && groupadd --system --gid "${DTK_GID}" dtk \
    && useradd --system --uid "${DTK_UID}" --gid "${DTK_GID}" --home-dir /srv --shell /usr/sbin/nologin dtk \
    && mkdir -p /profiles \
    && chown "${DTK_UID}:${DTK_GID}" /profiles \
    && chmod 0700 /profiles \
    && chown -R root:root /srv

USER dtk
EXPOSE 9000
ENTRYPOINT ["/usr/local/bin/browser-entrypoint"]
