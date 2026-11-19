# Ubuntu 24.04 for a current Mesa: Intel/AMD GPUs render through Vulkan when /dev/dri is
# passed in, and llvmpipe (software Vulkan) is the fallback when it isn't.
FROM ubuntu:24.04

ARG SOLIDCRAFT_VERSION=0.44.1
ARG SOLIDCRAFT_SHA256=164097743f6ff11c1eeb90a4313964728955e297689052053e4e5d8d20a64229

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 DEBIAN_FRONTEND=noninteractive \
    PATH=/opt/venv/bin:/opt/solidcraft/bin:$PATH

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl ffmpeg python3 python3-venv \
      mesa-vulkan-drivers libvulkan1 libgl1 libegl1 libfontconfig1 \
      libxkbcommon0 libwayland-client0 libx11-6 libxcursor1 libxrandr2 libxi6 \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL -o /tmp/sc.tgz \
      "https://github.com/tangency-labs/solidcraft/releases/download/v${SOLIDCRAFT_VERSION}/solidcraft-${SOLIDCRAFT_VERSION}-linux-x86_64.tar.gz" \
    && echo "${SOLIDCRAFT_SHA256}  /tmp/sc.tgz" | sha256sum -c - \
    && mkdir -p /opt/solidcraft && tar xzf /tmp/sc.tgz -C /opt/solidcraft --strip-components=1 \
    && rm /tmp/sc.tgz && test -x /opt/solidcraft/bin/solidcraft-cli

WORKDIR /app
COPY pyproject.toml README.md ./
COPY sklent/ ./sklent/
RUN python3 -m venv /opt/venv && pip install .

VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=4 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health', timeout=3)"
CMD ["sklent", "serve"]
