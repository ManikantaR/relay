# MEMORY.md — <project name>

> Per-project handoff log. Lives in THIS project's repo (not Relay's), so work context stays
> in the work repo and personal stays personal. Newest entry on top. The control plane appends
> skeleton entries on dispatch / Tier-2 hold / block; the agent adds what it learned; the owner
> edits freely.
>
> Copy this file to the root of a project when you onboard it to Relay.

## Format
```
## <ISO date> · <machine> · <author>
Did:     <what changed this session>
Next:    <the single most useful thing to do next>
Blocked: <waiting on owner / external / none>
Notes:   <gotchas worth remembering: a flaky test, a tricky module, a decision and why>
```

---

## <ISO date> · <machine> · owner
Did:     Onboarded to Relay. Generated .crew/ (tier2-paths, protected-tests, project.md).
Next:    First dispatch.
Blocked: none.
Notes:   <e.g. which paths are Tier-2 and why; which tests are the real gates>
