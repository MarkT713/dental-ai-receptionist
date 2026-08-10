FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DENTAL_SEED_DEMO_DATA=true

WORKDIR /app
COPY pyproject.toml README.md ./
COPY practice_management_software ./practice_management_software
COPY voice_pipeline ./voice_pipeline
COPY scripts ./scripts
COPY evals ./evals
RUN pip install --no-cache-dir .

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"
CMD ["uvicorn", "main:app", "--app-dir", "practice_management_software", "--host", "0.0.0.0", "--port", "8000"]
