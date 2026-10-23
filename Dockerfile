# Official multi-architecture image supports amd64, arm64 and arm/v7.
FROM python:3.11-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DOGBOT_DB=/data/dogbot.db \
    DOGBOT_LOCK=/data/dogbot.db.lock \
    DOGBOT_HEALTH=/data/dogbot.db.health.json
WORKDIR /app
RUN groupadd --gid 10001 dogbot \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin dogbot \
    && mkdir /data && chown 10001:10001 /data
COPY dogbot.py dogbotctl.py run.sh /app/
RUN chmod 755 /app/run.sh
USER 10001:10001
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD ["python3", "/app/dogbotctl.py", "healthcheck"]
ENTRYPOINT ["python3", "/app/dogbotctl.py"]
CMD ["run"]
