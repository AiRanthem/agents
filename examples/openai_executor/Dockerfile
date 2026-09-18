# Build from this directory:
#   docker build -t cedex-executor .
FROM node:22-bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
		bash \
		ca-certificates \
		curl \
		git \
		python3 \
		python3-pip \
		python3-venv \
	&& rm -rf /var/lib/apt/lists/*

# Official self-hosted environment install: npm install -g @openai/codex@alpha
RUN npm install -g @openai/codex@alpha \
	&& command -v codex \
	&& codex exec-server --help >/dev/null

COPY connect-openai openai-executor-daemon /usr/local/bin/
RUN chmod 0755 /usr/local/bin/connect-openai /usr/local/bin/openai-executor-daemon \
	&& mkdir -p /workspace

WORKDIR /workspace
CMD ["/usr/local/bin/openai-executor-daemon"]
