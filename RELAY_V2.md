# Relay v2 Architecture Spec

Status: draft
Date: 2026-06-25
Scope: runtime, persistence, session model, review loop, model policy, API, operator surfaces

## 1. Purpose

Relay v2 turns the current CLI-centered control plane into a session-oriented orchestration
system that can run continuously on a laptop or NAS, support multiple repos per user, expose a
real API for desktop and web clients, and preserve Relay's safety model:

- the owner owns the work item and the merge
- workers are disposable
- state lives on disk
- Tier-2 remains a structural human gate

The product target is:

1. personal development on a laptop
2. continuous personal runtime on a NAS / homelab
3. team-sharable framework where each engineer runs their own Relay locally


## 2. Non-goals

Relay v2 does not attempt to:

- replace GitHub or TFS as the planning system
- become a hosted multi-tenant SaaS
- auto-merge PRs
- make Telegram the primary control surface
- make `tmux` the runtime contract


## 3. Principles

1. State lives on disk. Recovery must work from files first.
2. The worker runtime is not the UI model.
3. Session control must be provider-agnostic.
4. Native operator surfaces come first; custom dashboards are secondary.
5. Review is a first-class workflow, not an afterthought.
6. Model selection should be policy-driven by default and overrideable when needed.


## 4. Runtime Architecture

### 4.1 Core processes

Relay v2 consists of one daemon per user plus one worker process per active session.

- `relayd`
  - long-running daemon
  - owns queue polling, dispatch, worker registry, policy evaluation, notifications,
    persistence, review loop coordination, and API serving
- worker session process
  - one-shot implementer or reviewer process
  - owns task execution only
  - runs against one repo worktree and one session brief

### 4.2 Environment strategy

- personal laptop
  - `relayd` runs locally
  - VS Code talks to local API
- NAS / homelab
  - `relayd` runs as the durable service
  - web UI and API are served from the daemon on LAN
- work Windows laptop
  - `relayd` runs locally
  - VS Code and terminal remain the primary surfaces

### 4.3 Service supervision

`relayd` should be supervised by the host environment rather than by `tmux`.

- NAS container: Docker restart policy or equivalent
- Linux host: `systemd` user or service unit if running outside Docker
- Windows: login-started process or Scheduled Task

`tmux` may remain available on Unix-like hosts as an optional attach/debug adapter, but it is
not the session model or required runtime substrate.


## 5. Session Model

### 5.1 Session abstraction

A worker is represented as a session, not as a shell window.

Session roles:

- `implementer`
- `reviewer`
- `triage` (later)

Session lifecycle properties:

- one-shot process
- resumable from disk state
- attachable / detachable
- PTY-backed when interactive control is needed
- auditable

### 5.2 Session states

Canonical session states:

- `queued`
- `dispatching`
- `running`
- `paused`
- `awaiting_input`
- `rate_limited`
- `review_requested`
- `review_running`
- `changes_requested`
- `approved`
- `held`
- `needs_decision`
- `done`
- `error`
- `terminated`

### 5.3 Resume semantics

Resume does not mean preserving the same PID. It means:

1. the daemon reads the session artifact set from disk
2. it reconstructs the brief and operator/reviewer history
3. it spawns a fresh process with the current checkpoint
4. the new process continues from the latest known session state

Workers must not restart from the beginning unless the operator explicitly requests a reset.


## 6. Persistence Model

### 6.1 Dual storage

Relay v2 uses both:

- canonical JSON/event files on disk
- a SQLite index for fast query, filtering, replay, and UI access

Disk artifacts remain the source of truth. SQLite is a query/index layer.

### 6.2 Directory layout

Suggested layout under `DATA_DIR`:

```text
data/
  sessions/
    <session-id>/
      session.json
      events.jsonl
      transcript.log
      checkpoints/
      evidence/
      attachments/
  workers/
    <session-id>.pid
  queue/
  cache/
  relay.db
```

### 6.3 Disk-first recovery rule

If SQLite is missing or corrupt, Relay must be able to rebuild index state from:

- `session.json`
- `events.jsonl`
- evidence artifacts
- transcript logs


## 7. Schemas

### 7.1 `session.json`

Suggested canonical schema:

```json
{
  "session_id": "sess_01...",
  "task_id": "smartocrprocess-12",
  "repo": "ManikantaR/smartocrprocess",
  "project_path": "/workspace/smartocrprocess",
  "worktree_path": "/workspace/.worktrees/smartocrprocess-12",
  "role": "implementer",
  "tier": "1",
  "state": "running",
  "lane": "claude",
  "provider": "anthropic",
  "model": "claude-sonnet-4-6",
  "effort": "medium",
  "selection_mode": "auto",
  "selection_reason": "tier-1 implementer default",
  "alternatives": [
    {
      "provider": "openai",
      "model": "gpt-5.4",
      "effort": "medium",
      "reason": "cost/latency alternative"
    }
  ],
  "operator_overrides": [],
  "review_round": 0,
  "max_review_rounds": 3,
  "parent_session_id": null,
  "review_session_id": null,
  "brief_path": "brief.md",
  "transcript_path": "transcript.log",
  "events_path": "events.jsonl",
  "evidence_dir": "evidence",
  "cost": {
    "input_tokens": 0,
    "output_tokens": 0,
    "usd_estimate": 0.0
  },
  "created_at": "2026-06-25T00:00:00Z",
  "updated_at": "2026-06-25T00:00:00Z",
  "started_at": null,
  "ended_at": null
}
```

### 7.2 `events.jsonl`

Each line is one append-only event.

Required fields:

```json
{
  "event_id": "evt_01...",
  "session_id": "sess_01...",
  "type": "operator_nudge",
  "timestamp": "2026-06-25T00:00:00Z",
  "actor": "owner",
  "summary": "Refocus on acceptance criterion 2",
  "payload": {},
  "sequence": 18
}
```

### 7.3 Event types

Minimum initial event set:

- `session_created`
- `session_started`
- `session_paused`
- `session_resumed`
- `session_terminated`
- `state_changed`
- `checkpoint_written`
- `operator_nudge`
- `operator_raw_input`
- `worker_acknowledged`
- `review_requested`
- `review_comment_added`
- `review_approved`
- `review_changes_requested`
- `review_loop_capped`
- `model_selected`
- `model_escalated`
- `lane_switched`
- `rate_limited`
- `needs_decision`
- `evidence_written`
- `cost_updated`


## 8. PTY and Interaction Model

### 8.1 Core requirement

Relay must own a brokered interaction channel to each live worker:

- stdout / stderr capture
- stdin injection
- interrupt / pause
- attach / detach

This is the primitive required to view, nudge, redirect, and control workers.

### 8.2 Control actions

Supported actions:

- `pause`
- `resume`
- `terminate`
- `send_nudge`
- `send_raw_input`
- `request_checkpoint`
- `reroute_model` (future)
- `reroute_lane` (future)

### 8.3 Pause semantics

Operator nudges pause immediately in protocol terms:

1. daemon sends interrupt/pause
2. worker stops after the current atomic tool step if a step is in progress
3. worker emits `session_paused`
4. daemon appends the operator instruction
5. worker emits `worker_acknowledged`
6. worker updates plan and resumes

This is immediate from the operator perspective without corrupting an in-flight tool call.

### 8.4 Nudge types

Structured nudge schema:

- `goal_correction`
- `acceptance_clarification`
- `code_example`
- `review_feedback`
- `operator_override`

Raw terminal input remains available for exceptional cases only.


## 9. Review Loop Engine

### 9.1 Roles

- implementer can modify code
- reviewer is branchless and read-only

Reviewer sees:

- full worktree diff
- evidence bundle
- transcript
- session timeline

### 9.2 Loop

1. implementer reaches review-ready state
2. daemon spawns reviewer session
3. reviewer produces line-specific comments where possible
4. daemon appends reviewer feedback to the same brief
5. implementer resumes from disk state
6. reviewer re-checks on the next round

### 9.3 Cap

Default cap: `3` review rounds.

On cap reached:

- emit `review_loop_capped`
- set session to `needs_decision`
- notify owner

### 9.4 Escalation

Relay may auto-upgrade model strength once per session family when:

- a review round fails on substance
- the diff is large
- the diff touches sensitive paths

After one automatic upgrade, further escalation requires human decision.


## 10. Tier-2 and Risk Handling

### 10.1 Existing risk source

The initial risk source remains `.crew/tier2-paths.txt`.

Future richer risk taxonomy can be added later, but v2 starts with the current repo-local
Tier-2 path model.

### 10.2 Tier-2 defaults

Tier-2 recommendations:

- implementer default effort: `medium`
- reviewer default effort: `medium`
- escalate reviewer to `high` only when needed

Tier-2 still requires human line-by-line review before merge.

### 10.3 Large diff heuristic

Initial heuristic:

- `files_changed >= 8`
- or `loc_changed >= 400`

Either threshold marks a diff as large for recommendation/escalation logic.


## 11. Model and Provider Policy

### 11.1 Policy location

Add repo-local model policy in `.crew/models.yml`.

Resolution order:

1. operator override
2. repo-local `.crew/models.yml`
3. user-global defaults
4. environment-allowed provider set

### 11.2 Policy goals

Model policy must support:

- per-role defaults
- per-environment restrictions
- auto selection
- visible competing recommendations
- provider pin only
- provider + model pin
- provider + model + effort pin

### 11.3 Initial provider constraints

- personal: allow configured personal providers/lane backends
- work: restrict to sanctioned providers only
  - current target: `copilot + claude`

### 11.4 Initial recommendation behavior

Default dispatch behavior:

- Relay auto-selects a recommended provider/model/effort
- Relay shows alternatives and reasons
- operator may confirm or override

Telegram dispatch should still require confirmation before execution.

### 11.5 Sample `.crew/models.yml`

```yaml
models:
  defaults:
    implementer:
      personal:
        preferred:
          - provider: anthropic
            model: claude-sonnet-4-6
            effort: medium
          - provider: openai
            model: gpt-5.4
            effort: medium
      work:
        preferred:
          - provider: copilot
          - provider: anthropic
            model: claude-sonnet-4-6
            effort: medium

    reviewer:
      personal:
        preferred:
          - provider: openai
            model: gpt-5.4
            effort: medium
          - provider: anthropic
            model: claude-opus-4-8
            effort: medium
      work:
        preferred:
          - provider: anthropic
            model: claude-sonnet-4-6
            effort: medium

  tier2:
    implementer:
      effort: medium
    reviewer:
      effort: medium
      escalate_to_high_on:
        - failed_review_round
        - sensitive_paths
        - large_diff

  escalation:
    max_review_rounds: 3
    auto_upgrade_once: true
    prefer_same_provider: true
```


## 12. API

### 12.1 Transport

Relay v2 exposes:

- local REST API
- local WebSocket stream

CLI remains available as a compatibility and scripting surface, but it should call the daemon
or shared library rather than remain the primary protocol between components.

### 12.2 REST endpoints

Initial REST surface:

- `GET /api/health`
- `GET /api/queue`
- `GET /api/sessions`
- `GET /api/sessions/{id}`
- `GET /api/sessions/{id}/timeline`
- `GET /api/sessions/{id}/transcript`
- `GET /api/sessions/{id}/diff`
- `GET /api/review`
- `POST /api/dispatch`
- `POST /api/sessions/{id}/pause`
- `POST /api/sessions/{id}/resume`
- `POST /api/sessions/{id}/terminate`
- `POST /api/sessions/{id}/nudge`
- `POST /api/sessions/{id}/raw-input`
- `POST /api/sessions/{id}/request-review`
- `POST /api/sessions/{id}/ack-decision`
- `GET /api/costs`
- `GET /api/models/recommendations`

### 12.3 WebSocket events

Initial push events:

- `session.created`
- `session.updated`
- `session.state_changed`
- `session.paused`
- `session.resumed`
- `session.terminated`
- `session.rate_limited`
- `session.needs_decision`
- `timeline.event`
- `review.updated`
- `queue.updated`
- `cost.updated`


## 13. Operator Surfaces

### 13.1 VS Code

VS Code remains the first desktop control surface.

Primary IA:

- `Queue`
- `Sessions`
- `Review`
- `Needs Decision`
- `Session Detail`

Session Detail is the main surface, not the board.

Session Detail should show:

- structured summary first
- transcript collapsed by default
- latest event
- changed files
- diff / evidence shortcuts
- model recommendation and alternatives
- nudge controls
- attach control

### 13.2 Web UI

Relay serves its own LAN web UI.

Goals:

- balanced read/control
- phone-friendly
- compact cards first
- session drill-down second

Mobile day-1 scope:

- queue
- dispatch
- active sessions
- latest status
- pause/resume
- send nudge

Full raw terminal streaming is not required for mobile v1.

### 13.3 Telegram

Telegram is ChatOps-lite, not the primary control plane.

Allowed initial commands:

- `/status`
- `/queue`
- `/sessions`
- `/dispatch <id>`
- `/pause`
- `/resume`
- `/hold <session-id>`
- `/nudge <session-id> <message>`

Avoid using Telegram for:

- raw terminal streaming
- full Tier-2 review flow
- detailed multi-step code intervention


## 14. Auth and Network Model

### 14.1 LAN deployment

The NAS web UI/API is served on LAN only by default.

### 14.2 Initial auth

Initial auth should be simple but real:

- username/password
- secure local password hash
- session cookie
- CSRF protection
- optional trusted device token later

GitHub OAuth is not required for v1.


## 15. Cost and Usage Reporting

Relay should report estimated usage at:

- session level
- repo level
- day level

Each session should record:

- input tokens
- output tokens
- estimated USD
- provider/model/effort used


## 16. Implementation Phases

### Phase 1: Session Core

- add session and event schemas
- write canonical disk artifacts
- add SQLite index
- implement state machine
- implement replay/timeline layer

### Phase 2: Review Loop Engine

- spawn reviewer sessions
- line-specific feedback artifact format
- same-brief review feedback appending
- review loop cap
- single automatic model escalation

### Phase 3: Daemon and API

- introduce `relayd`
- move core lifecycle logic behind REST/WebSocket
- keep CLI as compatibility client

### Phase 4: VS Code Redesign

- rebuild extension around sessions and session detail
- reduce reliance on heavy custom kanban
- integrate attach, nudge, timeline, evidence, and recommendation views

### Phase 5: Web UI

- LAN-hosted operator UI
- compact cards + session detail
- mobile-friendly dispatch and nudge flow

### Phase 6: Telegram

- notifications plus limited control
- confirmation flow for dispatch


## 17. Migration Plan from Current Relay

1. preserve current task directory artifacts where possible
2. add new session/event artifacts alongside current `status.md`/`worker.log`
3. introduce an adapter that derives v2 session state from v1 artifacts during migration
4. move spawner backends behind a session runtime interface
5. keep current CLI commands functional while daemon-backed commands replace direct file reads


## 18. Main Risks

1. PTY portability across macOS/Linux/Windows is the hardest runtime edge.
2. Mixing terminal interaction and structured event semantics can drift unless the protocol is
   explicit.
3. Review loops can become expensive if escalation and cap rules are weak.
4. LAN web control needs real auth from day 1; "just a password" without session/CSRF hygiene
   is too weak.
5. If the UI is built before the state machine settles, rework will be high.


## 19. Immediate Next Deliverables

The next implementation artifacts should be:

1. `session.json` schema definition
2. `event.json` schema definition
3. SQLite schema
4. session state machine document
5. `.crew/models.yml` parser and validator
6. daemon API contract

Those are the contracts the runtime and UI should build on.
