FROM python:3.12-slim

WORKDIR /app
COPY services/handu-m00-bridge/handu_m00_bridge /app/handu_m00_bridge
COPY services/handu-m06-lucylab/run.py /app/run.py
RUN pip install --no-cache-dir "asyncpg>=0.30,<1" "av>=14,<17" "httpx>=0.28,<1" "mcp>=2,<3" "uvicorn>=0.30,<1"

ENV PYTHONUNBUFFERED=1
CMD ["python", "/app/run.py"]
