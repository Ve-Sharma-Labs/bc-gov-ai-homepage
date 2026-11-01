FROM python:3.14.0-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production
WORKDIR /app
COPY apps/api/requirements.lock /app/requirements.lock
RUN --mount=type=secret,id=pip_config,target=/etc/pip.conf \
    python -m pip install --no-cache-dir -r /app/requirements.lock
COPY apps/api/pyproject.toml /app/apps/api/pyproject.toml
COPY apps/api/src /app/apps/api/src
RUN --mount=type=secret,id=pip_config,target=/etc/pip.conf \
    python -m pip install --no-cache-dir --no-deps /app/apps/api \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --no-create-home app
COPY data/pilot-catalog.json /app/data/pilot-catalog.json
COPY data/demo-personas.json /app/data/demo-personas.json
COPY data/demo-program-rules.json /app/data/demo-program-rules.json
COPY data/conversation-grounding-packs.json /app/data/conversation-grounding-packs.json
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"
CMD ["python", "-m", "uvicorn", "bc_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
