# SKILL: relay-onboard

Walk into any repo and produce a correct `.crew/` policy for it — by **scanning to propose,
then interviewing to confirm** (mode C). You never finalize without the owner's review.

## When to use
The owner runs this once per project before Relay works on it: "onboard this repo to Relay."

## Procedure

### 1. Scan to propose (do this before asking anything)
Inspect the repo and propose a Tier-2 set from signals — do not rely on the owner's memory:
- filenames/paths matching: `crypto`, `encrypt`, `decrypt`, `key`, `secret`, `auth`, `jwt`,
  `token`, `pii`, `migration`, `payment`, `billing`, `card`
- imports of crypto/secret libraries (language-appropriate: `crypto`, `jose`, `bcrypt`,
  `libsodium`, KMS/secrets-manager SDKs)
- files that read env secrets or `.env`
- migration directories
Present the proposed Tier-2 list as globs and say plainly: "these are my guesses, correct them."

### 2. Interview to confirm (one question at a time)
Ask, and wait for answers:
- "Which of these are truly sacred — a subtle bug leaks secrets/PII/money?" (prune/extend the list)
- "Any sensitive paths I missed that don't match obvious names?" (large work repos often have these)
- "For each Tier-2 path: does a gating test already exist, or does one need authoring?"
- "What is the TFS area path or `@relay` convention for pickup?" (sets `RELAY_AREA`)

### 3. Protected-test gap handling (policy: unguarded_tier2 = file-issue)
For every confirmed Tier-2 path:
- If a gating test exists → add it to `.crew/protected-tests.txt` (mark it protected).
- If none exists → **do not let the crew proceed unguarded.** File an issue titled
  "Relay: Tier-2 path `<path>` has no protected test" describing what test is needed
  (e.g. encrypt/decrypt round-trip, tamper detection, key-rotation correctness). This is
  owner/team work, not crew work.

### 4. Emit for review (never auto-commit)
Write these files and then STOP and ask the owner to review them before any commit:
- `.crew/tier2-paths.txt` — confirmed globs, one per line
- `.crew/protected-tests.txt` — existing gating tests only
- `.crew/project.md` — `mode: no-mistakes` (always), `RELAY_AREA: <value>`, and a short
  note of which Tier-2 paths are awaiting a protected test (cross-referencing the filed issues)

Print a summary: proposed Tier-2 set, which paths are guarded vs awaiting-a-test, the filed
gap issues, and the pickup fence. Explicitly invite correction. The owner reviews and commits.

## Hard rules
- Never mark a test protected that the crew authored — protected tests are owner/team-owned.
- Never finalize `.crew/` without the owner seeing it (mirrors the Tier-2 desk-review discipline).
- `mode` is always `no-mistakes`; never emit `+yolo`.
