\
FROM mcr.microsoft.com/devcontainers/python:1-3.12-bookworm

# The base image ships an apt source for yarn with no importable key, which breaks
# `apt-get update` outright (this project needs neither node nor yarn).
RUN rm -f /etc/apt/sources.list.d/yarn.list

# GitHub CLI (renv pr / renv clone's org discovery; also used by contributor tooling).
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
        > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/*

# uv + nox (see README.md "Development" and AGENTS.md for the command list this drives).
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"
RUN uv tool install nox

# asciinema (docs/assets/casts/) -- static binary, matched to the container's arch, so demo
# GIFs can be regenerated in a consistent environment instead of "works on my machine".
ARG ASCIINEMA_VERSION=v3.2.1
RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "$arch" in \
        amd64) rust_arch="x86_64-unknown-linux-gnu" ;; \
        arm64) rust_arch="aarch64-unknown-linux-gnu" ;; \
        *) echo "unsupported arch: $arch" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /usr/local/bin/asciinema \
        "https://github.com/asciinema/asciinema/releases/download/${ASCIINEMA_VERSION}/asciinema-${rust_arch}"; \
    chmod +x /usr/local/bin/asciinema

# agg: built from source via cargo rather than the prebuilt release binaries, which are
# glibc-version-sensitive (the x86_64-gnu release needs a newer glibc than Debian bookworm
# ships, so it fails at runtime with a GLIBC_2.38 not-found error; there's no aarch64-musl
# release to fall back to either). Building against this image's own toolchain sidesteps
# that entirely, at the cost of a slower image build.
ARG AGG_VERSION=v1.9.0
RUN curl -fsSL https://sh.rustup.rs | sh -s -- -y --profile minimal
ENV PATH="/root/.cargo/bin:${PATH}"
RUN cargo install --locked --tag "${AGG_VERSION}" --git https://github.com/asciinema/agg agg \
    && mv /root/.cargo/bin/agg /usr/local/bin/agg \
    && rustup self uninstall -y

# ffmpeg (only needed to re-measure a GIF's crop height when regenerating a taller demo; see
# docs/assets/casts/README.md).
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
