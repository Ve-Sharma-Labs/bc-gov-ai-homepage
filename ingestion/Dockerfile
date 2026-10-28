FROM python:3.14.0-slim-bookworm AS dependencies
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY ingestion/requirements.lock /app/requirements.lock
RUN --mount=type=secret,id=pip_config,target=/etc/pip.conf \
    python -m pip install --no-cache-dir -r /app/requirements.lock

FROM dependencies AS runtime
COPY ingestion/pyproject.toml /app/ingestion/pyproject.toml
COPY ingestion/bc_ingestion /app/ingestion/bc_ingestion
RUN python -m pip install --no-cache-dir --no-build-isolation --no-deps /app/ingestion \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --no-create-home app \
    && mkdir -p /app/ingestion/.generated \
    && chown app:app /app/ingestion/.generated
COPY data/pilot-catalog.json data/source-programme.json /app/data/
USER 10001:10001
ENTRYPOINT ["python", "-m", "bc_ingestion"]
CMD ["programme"]
