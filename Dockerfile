FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATABASE_PATH=/data/livros.db \
    PORT=8000

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && mkdir -p /data \
    && groupadd --system app \
    && useradd --system --gid app --home-dir /app app \
    && chown app:app /data

COPY --chown=app:app server.py .
COPY --chown=app:app acervo ./acervo

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os; from urllib.request import urlopen; urlopen('http://127.0.0.1:%s/' % os.environ.get('PORT', '8000'), timeout=3)" || exit 1

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "4", "--timeout", "60", "--access-logfile", "-", "--error-logfile", "-", "acervo:create_app()"]
