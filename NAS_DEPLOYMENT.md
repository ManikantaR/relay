# Deploying Relay — home (NAS / Docker) and work (laptop / native)

Relay runs in **two environments with one engine**. Policy travels with each repo (`.crew`);
only the *runtime* and the *lane fleet* differ.

| | **Home** | **Work** |
|---|---|---|
| Host | UGREEN NAS (always-on) | work laptop (Windows) |
| Runtime | **Docker** container (CLIDE base + agy + relay) | **native** — no Docker |
| Profile | `RELAY_PROFILE=personal` | `RELAY_PROFILE=work` + `RELAY_STRICT_LANES=1` |
| Board / notify | GitHub Issues / Telegram | TFS / Teams |
| Lanes | `copilot,agy,codex,claude` | only org-sanctioned (e.g. `claude` or `copilot`) |
| Spawner | tmux (in container) | `wt-tab` / `bg-job` (relay's Windows ladder) |
| Watch | ttyd web terminal · Telegram · `ssh nas` | the wt-tab windows on the laptop |

The NAS is what makes home **continuous** — `relay watch` keeps supervising/auto-dispatching
while your Mac is closed. At work there's no always-on box, so relay runs on the laptop while
it's on; the disk-state design means it resumes cleanly next time it starts.

---

# Part A — Home: Relay on the NAS via Docker

## A1. Architecture

```
 Mac (browser / ssh) ──LAN──►  NAS : Docker
                               ┌──────────────────────────────────────────┐
                               │ relay container (restart: always)        │
                               │  • relay watch  (Python control plane)    │
                               │  • tmux session "relay" → worker windows  │
                               │  • claude · copilot · codex · agy · gh     │
                               │  • ttyd web terminal  :7681               │
                               │  • iptables egress allowlist (NET_ADMIN)  │
                               └──────────────────────────────────────────┘
   volumes (persist across restarts):
     /workspace        → bind mount: your managed repos + .worktrees + relay data/
     /root/.codex      → codex device-login creds (if used)
     /root/.agy        → agy creds (if device/browser login used)
   secrets: .env (gitignored) — long-lived subscription tokens, injected as env vars
```

The worker holds no board creds and only commits; the control plane (same container, trusted)
pushes branches and files PRs. Egress firewall means even a misbehaving worker can only reach
the allowlisted model/Git endpoints.

## A2. The image — adopt CLIDE, add agy + relay

`itscooleric/clide` already bundles claude + copilot + codex + gh + tmux + ttyd + the egress
firewall. We layer two things on top: the Antigravity CLI (`agy`) and relay itself.

```dockerfile
# Dockerfile.relay — build on CLIDE, add agy + relay
FROM clide:latest                       # built per CLIDE's Makefile, or pin a digest
# Antigravity CLI (the agy lane) — not in CLIDE
RUN curl -fsSL https://antigravity.google/cli/install.sh | bash && agy install
# relay itself (from your private repo, pinned to main)
RUN git clone https://github.com/<you>/relay /opt/relay
WORKDIR /workspace
# relay watch is the container's main process
CMD ["python3", "/opt/relay/py/relay_cli.py", "watch"]
```

```yaml
# docker-compose.yml (on the NAS)
services:
  relay:
    build: { context: ., dockerfile: Dockerfile.relay }
    restart: always
    cap_add: ["NET_ADMIN"]              # egress firewall
    env_file: [ .env ]                  # tokens (gitignored) — see A3
    environment:
      RELAY_PROFILE: personal
      RELAY_LANES: "copilot,agy,codex,claude"
      RELAY_PROJECT: /workspace/smartocrprocess
      RELAY_AUTODISPATCH: "0"          # flip to 1 only after a clean manual dry-run
      RELAY_MAX_WORKERS: "2"
      CLIDE_ALLOWED_HOSTS: "generativelanguage.googleapis.com,oauth2.googleapis.com,antigravity.google"
      TTYD_USER: relay
      TTYD_PASS: ${TTYD_PASS}
    volumes:
      - /volume1/relay/workspace:/workspace          # managed repos + worktrees + data/
      - /volume1/relay/creds/codex:/root/.codex      # if codex device login
      - /volume1/relay/creds/agy:/root/.agy          # if agy device login
    ports: [ "7681:7681" ]             # ttyd web terminal (LAN only; don't expose to WAN)
```

## A3. Auth — do it ONCE on your Mac, inject tokens (no browser in the container)

You're on subscriptions, so use **long-lived subscription tokens** as env vars. Generate each
on your Mac (which has a browser), drop into `.env` on the NAS (gitignored), `docker compose
up -d`. No interactive login happens inside the container.

| Lane / tool | Get the token on your Mac | Goes in `.env` as |
|---|---|---|
| **claude** (Max sub) | `claude setup-token` (valid ~1 year) | `CLAUDE_CODE_OAUTH_TOKEN=` |
| **gh + copilot** | GitHub PAT with **Copilot Requests** + `repo` scope | `GH_TOKEN=` |
| **codex** | `codex auth login --auth device` → creds land in `~/.codex` (mount it), or a key | `OPENAI_API_KEY=` *(or mount creds)* |
| **agy** (Gemini) | `agy login` (device/browser) → mount its creds dir, or a Gemini API key | `GEMINI_API_KEY=` *(or mount creds)* |
| git authorship | — | `GIT_AUTHOR_NAME=`, `GIT_AUTHOR_EMAIL=` |

> Rotation: when a token expires, regenerate it on the Mac, update `.env`, `docker compose up -d`.
> The startup lane auth-check (see AGENTS.md §12, once `relay_lanes.py` lands) drops any lane
> whose token has gone stale and announces it — never a silent dead lane.

> Honest ToS note: running a *subscription* harness headless/automated on a server is a gray
> area on some plans. If unsure, use API keys for that lane (pay-per-token) — relay treats them
> identically; only the rate-limit-failover value drops (you hit spend, not a window).

## A4. Where the code lives

- **Managed repos** are cloned into the bind-mounted volume: `/workspace/smartocrprocess`,
  `/workspace/MoneyPulse`, … Relay creates disposable worktrees under each repo's `.worktrees/`.
- **Branches** are per-task: `relay/<lane>-t<id>` (e.g. `relay/ag-t12`). The control plane
  pushes them to GitHub and files the PR; you merge there. Nothing long-lived lives only in the
  container — the volume + GitHub are the durable state, so a container rebuild loses nothing.
- **relay itself** runs from `main` (cloned in the image, or bind-mount `/opt/relay` to pull
  updates without rebuilding).

## A5. Connect from your Mac

1. **Telegram (primary)** — you don't watch terminals; you get `tier1-ready` / `tier2-held`
   pings and review the PR on GitHub.
2. **Web terminal** — `http://<nas-ip>:7681` (e.g. `http://10.140.1.95:7681`), login
   `TTYD_USER`/`TTYD_PASS`. Attaches to the `relay` tmux session — watch any worker window.
   Keep this **LAN-only**; never port-forward ttyd to the internet.
3. **SSH (intervene)** — `ssh nas` → `docker exec -it relay tmux attach -t relay`, then switch
   windows to watch or type into a worker.

## A6. First run

```bash
ssh nas && cd /volume1/relay
docker compose up -d --build
docker exec -it relay relay status          # should show "(no active workers)"
# manual dry-run ONE issue end-to-end before automating:
docker exec -it relay relay dispatch 12 --project /workspace/smartocrprocess --lane agy
# watch it: web terminal :7681, or relay status; PR lands held for your review.
# only after that proves out:  set RELAY_AUTODISPATCH=1, docker compose up -d
```

---

# Part B — Work: Relay native on the laptop

No Docker. Relay runs directly on the Windows laptop while it's on.

```powershell
# one-time
git clone https://github.com/<you>/relay; cd relay
Copy-Item env.example.txt data\captain.work.md   # fill TFS_URL, TEAMS_WEBHOOK_URL, RELAY_AREA
# governance: only org-sanctioned lanes; hold explicit unsanctioned requests
$env:RELAY_PROFILE="work"; $env:RELAY_STRICT_LANES="1"; $env:RELAY_LANES="claude"
.\relay.ps1 watch
```

- Spawner uses the Windows ladder (`wt-tab` → `bg-job`); you watch the wt-tab windows locally.
- `RELAY_STRICT_LANES=1` → an explicit `lane:X` for an unsanctioned tool is **held + flagged**,
  never silently substituted (AGENTS.md §12).
- Auth is whatever your org sanctions; do not mount personal subscription tokens on a work box.

---

# Best practice / honest limits

- **Concurrency is the NAS's real limit.** Each worker is a full agent process; start
  `RELAY_MAX_WORKERS=2`, watch RAM, raise slowly. The 32GB NAS handles a small crew, not a swarm.
- **Keep the egress firewall ON.** It's the cheapest guarantee that an agent can't exfiltrate.
  Add hosts only via `CLIDE_ALLOWED_HOSTS`.
- **Auto-dispatch is opt-in for a reason.** Prove the loop on one manual dispatch first.
- **CLIDE logs full prompts/completions** to `/var/log/clide/intercept.jsonl` — fine on a
  single-user NAS, but treat that path as sensitive (it can contain code + secrets-in-context).
- **Continuity, not magic.** When every lane is rate-limited, the crew idles until a window
  reopens — relay resumes fast, it doesn't beat the ceiling. The NAS just means it's *there* to
  resume the moment it can.
