FROM python:3.12-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704

LABEL org.opencontainers.image.title="Dental AI Receptionist" \
      org.opencontainers.image.description="Human-approved synthetic dental intake and staff queue demo" \
      org.opencontainers.image.source="https://github.com/MarkT713/dental-ai-receptionist" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DENTAL_SEED_DEMO_DATA=true \
    DENTAL_DEMO_MODE=true \
    DENTAL_DB_PATH=/data/pms.db

WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /data \
    && chown app:app /data

COPY --chown=app:app practice_management_software ./practice_management_software
COPY --chown=app:app voice_pipeline ./voice_pipeline
COPY --chown=app:app scripts ./scripts
COPY --chown=app:app evals ./evals

USER 10001:10001
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"
CMD ["uvicorn", "main:app", "--app-dir", "practice_management_software", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]
