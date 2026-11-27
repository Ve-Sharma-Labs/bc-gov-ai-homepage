ARG JURISDICTION=bc
FROM python:3.14.10-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production
WORKDIR /app
COPY apps/api/requirements.lock /app/requirements.lock
RUN --mount=type=secret,id=pip_config,target=/etc/pip.conf \
    python -m pip install --no-cache-dir -r /app/requirements.lock
COPY apps/api/pyproject.toml /app/apps/api/pyproject.toml
COPY apps/api/src /app/apps/api/src
COPY ingestion/bc_ingestion/__init__.py ingestion/bc_ingestion/operation_rights.py ingestion/bc_ingestion/metadata.py ingestion/bc_ingestion/policy.py ingestion/bc_ingestion/pack_policy.py ingestion/bc_ingestion/robots.py /app/ingestion/bc_ingestion/
RUN --mount=type=secret,id=pip_config,target=/etc/pip.conf \
    python -m pip install --no-cache-dir --no-deps /app/apps/api \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --no-create-home app
FROM base AS selected-pack
ARG JURISDICTION=bc
ARG OPERATION_RIGHTS_REVIEW_SHA256=""
ENV JURISDICTION=${JURISDICTION} \
    OPERATION_RIGHTS_REVIEW_SHA256=${OPERATION_RIGHTS_REVIEW_SHA256}
COPY jurisdictions /source/jurisdictions
COPY data /source/data
RUN python -m bc_api.jurisdiction --root /source --stage /selected

FROM base AS runtime
ARG JURISDICTION=bc
ARG OPERATION_RIGHTS_REVIEW_SHA256=""
ENV JURISDICTION=${JURISDICTION} \
    BAKED_JURISDICTION=${JURISDICTION} \
    OPERATION_RIGHTS_REVIEW_SHA256=${OPERATION_RIGHTS_REVIEW_SHA256}
COPY --from=selected-pack /selected /app
RUN python -c "from bc_api.main import app; assert app.state.jurisdiction.id"
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"
CMD ["python", "-m", "uvicorn", "bc_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
