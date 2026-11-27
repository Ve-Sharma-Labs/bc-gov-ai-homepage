# Build from the repository root: docker build -f apps/web/Dockerfile .
FROM --platform=$BUILDPLATFORM node:24.22.3-alpine AS dependencies
WORKDIR /app
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM dependencies AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
ARG JURISDICTION=bc
ENV JURISDICTION=$JURISDICTION JURISDICTION_PACKS_ROOT=/jurisdictions
COPY jurisdictions/ /jurisdictions/
COPY apps/web/ ./
# Compile portable JavaScript natively; do not copy build-host native addons.
RUN npm run build && rm -rf /app/.next/standalone/node_modules

FROM node:24.22.3-alpine AS runtime-base
RUN apk upgrade --no-cache

FROM runtime-base AS runtime-dependencies
WORKDIR /app
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci --omit=dev --no-audit --no-fund
ARG JURISDICTION=bc
RUN if [ "$JURISDICTION" != "bc" ]; then rm -rf node_modules/@bcgov; fi

FROM runtime-base AS runtime
WORKDIR /app
ARG JURISDICTION=bc
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3000 JURISDICTION=$JURISDICTION NODE_OPTIONS="--require /app/scripts/jurisdiction-runtime.cjs"
RUN rm -rf /usr/local/lib/node_modules/npm /usr/local/bin/npm /usr/local/bin/npx \
    && addgroup -S -g 1001 web && adduser -S -u 1001 -G web web
COPY --from=build --chown=web:web /app/.next/standalone ./
COPY --from=runtime-dependencies --chown=web:web /app/node_modules ./node_modules
COPY --from=build --chown=web:web /app/.next/static ./.next/static
COPY --from=build --chown=web:web /app/public ./public
COPY --from=build --chown=web:web /app/.next/jurisdiction.json ./jurisdiction.json
COPY --from=build --chown=web:web /app/scripts/jurisdiction-runtime.cjs ./scripts/jurisdiction-runtime.cjs
USER web
EXPOSE 3000
CMD ["node", "server.js"]
