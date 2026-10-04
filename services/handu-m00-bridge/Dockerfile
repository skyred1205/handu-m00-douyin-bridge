FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY handu_m00_bridge ./handu_m00_bridge
RUN pip install --no-cache-dir .
ENV PYTHONUNBUFFERED=1
CMD ["sh", "-c", "uvicorn handu_m00_bridge.server:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
