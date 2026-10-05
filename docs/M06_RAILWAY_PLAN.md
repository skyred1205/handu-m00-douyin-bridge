# Railway M06

M06 will call LucyLab from the Railway gateway, keep the LucyLab credential only in Railway environment variables, store idempotency state in Postgres, and return voice WAV plus SRT as MCP resources. No credential is committed to GitHub.
