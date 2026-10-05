FROM python:3.12-slim

WORKDIR /app
COPY services/handu-m00-bridge/handu_m00_bridge /app/handu_m00_bridge
RUN pip install --no-cache-dir "asyncpg>=0.30,<1" "av>=14,<17" "httpx>=0.28,<1" "mcp>=2,<3" "uvicorn>=0.30,<1"

ENV PYTHONUNBUFFERED=1
CMD ["uvicorn", "handu_m00_bridge.m06_server:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers"]
