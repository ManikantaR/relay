# Relay Control — VS Code extension

Mission control for [relay](../) from inside your editor. **Local only** — no hosted server,
no exposed port; it drives the `relay` CLI through a configurable exec prefix, so the same
extension works against a local relay (work laptop) or the NAS container.

## What it gives you
- **Workers tree** (Relay sidebar) — every active worker: task · repo · lane · state, live.
- **Mission Control webview** — the parallel view, refreshing on a poll.
- **Status bar** — `relay: 3 active · 1 held`, click to open the dashboard.
- **One-click commands** — Pull & Dispatch, Dispatch Issue, Kill Worker, Open PRs,
  Pause/Resume auto-dispatch, Attach Terminal (drops you into the worker's tmux window).

## Settings
| Setting | Default | What |
|---|---|---|
| `relay.execPrefix` | `""` | Prefix before every `relay` call. Empty = local / Remote-SSH host. NAS from a local editor: `ssh nas docker exec -i relay`. |
| `relay.cwd` | `""` | Working dir for relay (defaults to the first workspace folder). |
| `relay.pollSeconds` | `5` | Status refresh interval. |

## Reaching the NAS — two ways
- **Remote-SSH** (cleanest): open the NAS over Remote-SSH; the extension runs there, terminals
  *are* the container's tmux. Leave `relay.execPrefix` empty.
- **Exec prefix**: keep VS Code local, set `relay.execPrefix` to `ssh nas docker exec -i relay`.

## Build / run (dev)
```bash
cd vscode
npm install
npm run compile
# press F5 in VS Code to launch an Extension Development Host
```

Requires `relay` reachable per `relay.execPrefix`, and (for `--json` status) the relay control
plane running. Consumes relay's machine-readable feed: `relay status|pull|lanes --json`.
