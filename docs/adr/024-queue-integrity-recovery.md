---
subject: queue-integrity-recovery
---

# Queue Integrity Recovery: Audit Inspects, Heal Restamps

## Status

Accepted (2026-07-12). Amends the frh-17 tamper-evidence contract (`docs/plans/frh-17-queue-mutation-guard.md`).

## Context

frh-17 made queue writes tamper-evident: `write_queue` stamps the wrapper with a monotonic `revision` and a `content_hash` over the canonical tasks dump, and `read_queue(verify=True)` raises `QueueIntegrityError` on mismatch. Mutating paths fail closed; read-only paths warn and continue.

A consuming project reported that the envelope has no tool-provided recovery path. `TaskBackend.load()` hard-codes `verify=True` — the interface has no `verify` parameter — so after any legitimate external edit (migration scripts, manual queue curation), _every_ command that loads the queue raises before doing work. The error message told users to run `aet state audit`, but `cmd_audit` died on the same check, and even had it run, audit never mutates so it could not restamp the hash. `cmd_heal` was equally bricked. The only escapes were manual hash recomputation or deleting the `content_hash` key.

## Decision

- `TaskBackend.load()` gains `verify: bool = True`, passed through to `read_queue` by the JSON-mirror backends (`JsonBackend`, `GitHubBackend`); `GitRefsBackend` accepts the flag for interface parity (its tamper-evidence is a separate work item).
- `audit` is the **diagnostic**: it loads with `verify=False`, reports the mismatch on stderr, and completes its stored-vs-derived report on the unverified data. It never mutates.
- `heal` is the **repair**: it loads with `verify=False`; `--apply` restamps the envelope (`revision` + `content_hash`, via a normal backend save) before applying any state fixes, so a successful heal always leaves the queue verifiable — including when there are no state discrepancies and only the envelope is stale. Dry-run heal never mutates.
- The `QueueIntegrityError` message names both commands: audit to inspect, `heal --apply` to repair.
- Mutating commands stay fail-closed; `aet-state`'s entry point now renders the error as a deliberate one-line refusal instead of a traceback.
- Because `queue.py` is loaded twice in-process (`aet_queue` by `aet-state`, `queue` by the backends), `QueueIntegrityError` exists as two distinct classes; `aet-state` catches both.

## Consequences

- A hand-edited or migration-touched queue is recoverable entirely through the CLI: audit to see the damage, `heal --apply` to restamp. The frh-17 error message is now true.
- Heal restamps without reverting: externally edited field values are preserved (the edit is treated as legitimate curation), only the envelope is refreshed.
- The fail-closed guarantee for mutating paths is unchanged; the new `verify` parameter defaults to `True`, so existing callers keep their behavior.
- Any future backend must accept `verify` on `load()`; backends without an integrity mechanism accept it as a no-op.

## Alternatives Considered

- **Wire `--force` into the load path to bypass verification on any command** — rejected: it weakens the fail-closed wall exactly where it matters (mutations on top of state the system did not write) and conflates lease override with integrity override, two unrelated guards.
- **A dedicated `aet state restamp` command** — deferred: heal already mutates state safely under the lease and lock, so restamping there adds no new surface. If a standalone restamp ever proves necessary (e.g. bulk migrations), it can reuse the same `backend.load(verify=False)` + `backend.save` path.
- **Make audit restamp when it finds zero discrepancies** — rejected: audit's contract is "never mutates"; silently writing from a diagnostic command would blur the inspect/repair boundary this ADR establishes.
