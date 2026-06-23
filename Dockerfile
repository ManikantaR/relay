# Relay container image — the home/NAS runtime.
#
# Extends CLIDE (github.com/itscooleric/clide), which already bundles claude + copilot +
# codex + gh + tmux + a ttyd web terminal + an iptables egress allowlist. We add the agy
# (Antigravity) lane and the relay control plane on top.
#
# Build CLIDE first (it isn't on a registry):
#     git clone https://github.com/itscooleric/clide && cd clide && make build   # -> clide:latest
# Then from the relay repo root:
#     docker compose build
#
# .dockerignore keeps secrets (relay.env, data/captain.*), git history, and runtime state
# OUT of the image — only relay's code is copied in.

FROM clide:latest

USER root

# The agy lane (not in CLIDE). Non-fatal if the installer changes — the lane auth-check
# (AGENTS.md §12) drops agy at runtime if it isn't actually available.
RUN curl -fsSL https://antigravity.google/cli/install.sh | bash && agy install || \
    echo "WARN: agy install failed at build; the agy lane will be dropped at runtime"

# relay control plane (build context = repo root; secrets excluded via .dockerignore)
COPY . /opt/relay
RUN ln -sf /opt/relay/relay /usr/local/bin/relay

ENV DATA_DIR=/workspace/.relay-data \
    RELAY_WORKTREES=.worktrees \
    RELAY_PYTHON=python3

WORKDIR /workspace

# The control plane is the container's main process: supervise + (opt-in) auto-dispatch.
# Pure Python — zero LLM tokens while idle. Workers are tmux windows it spawns.
CMD ["python3", "/opt/relay/py/relay_cli.py", "watch"]
