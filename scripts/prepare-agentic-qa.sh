#!/usr/bin/env bash
set -euo pipefail

python -m venv apps/api/.venv
apps/api/.venv/bin/python -m pip install --requirement=apps/api/requirements.lock --editable=apps/api
npm ci
npm --prefix apps/web ci
npm run build

nohup env \
  WEB_PORT=3310 \
  API_PORT=8310 \
  API_ALLOWED_ORIGINS=http://127.0.0.1:3310,http://localhost:3310 \
  API_ALLOWED_HOSTS=localhost,127.0.0.1,::1,api \
  API_AGENT_RUNS_PER_MINUTE=30 \
  APP_ENV=development \
  NEXT_TELEMETRY_DISABLED=1 \
  WEBIQ_ENABLED=false \
  SYNTHETIC_CONTEXT_ENABLED=true \
  AI_CONVERSATION_ENABLED=true \
  TASK_ASSISTANCE_ENABLED=true \
  GROUNDED_CONVERSATION_ENABLED=false \
  LOCAL_EVIDENCE_EVALUATION_ENABLED=false \
  FOUNDRY_PROJECT_ENDPOINT= \
  FOUNDRY_AGENT_NAME= \
  FOUNDRY_AGENT_VERSION= \
  FOUNDRY_AGENTS='[]' \
  AZURE_SEARCH_ENDPOINT= \
  REDIS_ENDPOINT= \
  APPLICATIONINSIGHTS_CONNECTION_STRING= \
  npm start >/tmp/agentic-qa-server.log 2>&1 &

for attempt in $(seq 1 90); do
  if curl --fail --silent http://127.0.0.1:3310/api/catalog >/dev/null; then
    exit 0
  fi
  sleep 2
done

cat /tmp/agentic-qa-server.log
exit 1
