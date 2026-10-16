# Linux image (CPU transcription with faster-whisper). On a Mac, run natively to use the Apple GPU.
FROM node:22-bookworm-slim AS connector
# Build tools for native modules without a prebuilt binary (e.g. @discordjs/opus on arm64).
RUN apt-get update && apt-get install -y --no-install-recommends python3 make g++ \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app/connector-discord
COPY connector-discord/package.json connector-discord/package-lock.json ./
RUN npm ci --omit=dev
COPY connector-discord/src ./src

FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
COPY --from=connector /usr/local/bin/node /usr/local/bin/node
COPY --from=ghcr.io/astral-sh/uv:0.8.13 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --extra faster
COPY --from=connector /app/connector-discord ./connector-discord
VOLUME ["/config", "/data"]
ENTRYPOINT ["uv", "run", "--no-sync", "kb-meeting-agent"]
CMD ["run", "--config", "/config/config.yml"]
