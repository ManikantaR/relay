# INSTALL — push Relay to your own GitHub

I can't push to your GitHub from here (this environment has no outbound network, and I don't
hold your credentials). Below is the 30-second copy-paste. Reviewing every file before the
first push is deliberate — Relay's own first commit should follow Relay's own rule: you read
it at a desk before it lands.

## 1. Review first
Open and read: `AGENTS.md`, `lib/policy.yml`, every `bin/*.sh`, `skill/SKILL.md`, and the
CI guard. Confirm the policy matches what we agreed. Correct the example `.crew/` globs to
your actual tree if you'll use it as a starting template.

## 2. Make it a repo and push

```bash
cd relay

# confirm secrets won't be committed (these are gitignored already)
cat .gitignore

git init
git add .
git commit -m "Relay: portable autonomous-agent orchestrator (two-tier leash, disk-state continuity)"

# create the repo on your account and push (GitHub CLI)
gh repo create relay --private --source=. --remote=origin --push

# …or with a remote you create manually:
# git remote add origin git@github.com:<you>/relay.git
# git branch -M main
# git push -u origin main
```

## 3. Per-environment secrets (never committed)
Create the profile file the notifier reads — it's gitignored:

```bash
# personal
cat > data/captain.personal.md <<'EOF'
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
EOF

# work (on your work laptop, after clearing agent use with your org)
cat > data/captain.work.md <<'EOF'
TEAMS_WEBHOOK_URL=https://outlook.office.com/webhook/...
RELAY_AREA=YourProject\\Area\\Path
EOF
```

## 4. Onboard a project
Pull Relay into the environment, launch your harness in the Relay directory, and run the
`relay-onboard` skill against a target repo. Review the generated `.crew/` files, then commit
them **into that project's repo** (not into Relay).

## 5. Before pointing it at a work repo
You said your org already sanctions agent-driven PRs with you reviewing every one — good.
Still worth confirming: the protected-test guard runs in your org's CI (consumes their
minutes), and the agent acts under your identity. Keep `RELAY_PROFILE=work` so notifications
go to Teams and pickup is fenced by `RELAY_AREA`.

## Not yet wired (honest gaps)
These are referenced by `AGENTS.md` but intentionally left for you, because they depend on
your exact harness/board setup and shouldn't be guessed:
- the lead's **board queries** for applying/reading `agent-ready`/`agent-wip`/`agent-review`
  on GitHub vs TFS (the lead does this via its tools; the labels and pickup rule are specified
  in AGENTS.md §2, but the concrete API calls are environment-specific)
- `relay-pr-check` / merge-poll helper (Tier-1 auto-skim close-out)
Tell me your board API surface (GitHub Issues API is easy; TFS/Azure DevOps work-item query
needs your org URL + PAT scope) and I'll write those too.

## Env file: download + rename
The template ships as `env.example.txt` (not `.env.example`) so it downloads cleanly.
After saving it, rename to the gitignored profile file and fill it:
```bash
cp env.example.txt data/captain.personal.md     # or data/captain.work.md
```

## GitHub auth (personal): no PAT
Relay's GitHub adapter uses the GitHub CLI. Make sure it's authenticated:
```bash
gh auth status          # if not logged in: gh auth login
```
No `GITHUB_TOKEN` needed. (Only consider a PAT if you later run `relay watch` on a NAS
where `gh` isn't authenticated.)

## TFS auth (work): your scripts own the PAT
Relay does not handle your TFS PAT. Your existing PowerShell scripts already read it from
their configured env. Relay only calls those scripts by path (`RELAY_TFS_SCRIPTS`).
