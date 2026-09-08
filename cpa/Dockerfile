ARG CLI_PROXY_IMAGE=eceasy/cli-proxy-api:latest
FROM ${CLI_PROXY_IMAGE}

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
