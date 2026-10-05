ARG DTK_TAG=sha-31d56df1462e99f24621eb2c6f060af183bf24fd
FROM evil0ctal/douyin_tiktok_download_api-downloader:${DTK_TAG} AS downloader
FROM evil0ctal/douyin_tiktok_download_api:${DTK_TAG}

USER root
COPY --from=downloader /usr/local/bin/downloader /usr/local/bin/downloader
COPY services/handu-m00-bridge/handu_m00_bridge /app/handu_m00_bridge
COPY services/handu-dtk-gateway/gateway.py /app/handu_gateway.py
RUN pip install --no-cache-dir "av>=14,<17" \
    && install -d -o dtk -g dtk -m 0750 /var/lib/dtk/media /var/lib/handu /var/lib/handu/m00-cache /var/lib/handu/m06-cache

USER dtk
WORKDIR /app
ENTRYPOINT []
CMD ["python", "/app/handu_gateway.py"]
