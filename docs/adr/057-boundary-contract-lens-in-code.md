---
subject: boundary-contract-lens
---

# Boundary-Contract Lens Rides the Review Verdict in Code

## Status

Accepted (2026-08-10). Implements R-6 from `docs/prds/structural-review-tier-2-prd.md`.

## Context

ADR-008 declared the API boundary contract a hard gate in prose: when a vertical slice touches both a backend response shape and a frontend consumer, an agreement test must exist. Consumer telemetry shows this was declared-and-not-effective — 25 of 111 consumer defects are this class (wrappers leaking into component state, snake_case reaching camelCase, frontend calling nonexistent endpoints). Prose gating depends on reviewer recall, and reviewer recall fails under pressure.

The trigger mechanism already exists: ADR-049's `src/aet/change_scope.py:changed_paths()` returns the changed-file set. The only remaining question is where to enforce the check and how to report its outcome.

## Decision

1. **A new module, `src/aet/boundary.py`, implements the mechanical lens.** It classifies paths as response-shape files (serializers, controllers, schemas, resources, DTOs) or client-consumer files (components, repositories, api-clients, hooks, stores) using default pattern tables, and searches `tests/` for an agreement test. An agreement test is either:
   - a test that references both a changed shape file and a changed consumer file, or
   - a test that uses a boundary-mock marker (`msw`, `nock`, `Http::fake`, `mirage`).

2. **Pattern tables and markers are overridable via `.agents/aet-config.json`.** The `boundary_contract` key holds `shape_patterns`, `consumer_patterns`, and `marker_vocabulary`. This preserves ADR-048's two-layer config model and lets projects adapt the lens to their own naming conventions.

3. **The lens rides the existing `review` verdict, not a new gate kind.** A new `boundary` gate kind would require a `evidence.SCHEMAS` entry, a new `software.json` stage, `KIND_TO_STAGE`/`KIND_TO_SKILL` mappings, and an owning skill. The `review` schema already carries a `findings: list`, and review is an ungated always-run stage (`src/aet/gate.py:22`). The `review` SCHEMAS entry is deliberately **not** extended with a required key, because required keys invalidate existing payloads.

4. **The lens is enforced in `src/aet/cli/gate.py` on `aet gate submit --stage review`.** When the lens trips, the command refuses the verdict, prints a named error, and exits 1 even when `--verdict pass` is declared. This is fail-closed enforcement on the sole-writer path (G1), with no prose writer around it.

5. **Lens outcomes are recorded in two places.** On pass/n-a, the gate appends a structured `boundary-contract` finding to the review payload's `findings`, and adds a `boundary_contract_lens` object to the ledger `verdict` event payload. Existing schemas stay unchanged.

6. **`src/aet/change_scope.py` maps `src/aet/boundary.py` to `tests/test_boundary.py`** so ADR-049 scoped validation covers the new module.

7. **The parked `docs/plans/cov-04-review-tests-lens.md` is superseded.** Its part (a) — new-file coverage completeness — already lives as prose in `skills/aet-review/SKILL.md` and `skills/aet-review/references/test-coverage-check.md` §1–2. Its part (b) — the API boundary check — is subsumed by this code gate. Formal queue/state closure of cov-04 is handled at scope validation, not in this diff.

## Consequences

- The boundary-contract defect class is blocked structurally rather than by reviewer memory.
- No new gate kind, stage, schema, or skill is introduced; the change is localized to one module, one CLI integration point, and skill documentation updates.
- Existing review verdict payloads remain valid; the lens outcome is additive data inside `findings` and the ledger payload.
- Projects with non-standard naming can override the classifier without forking the toolkit.
- The `aet-review` skill's Tests lens is simplified: the boundary-contract half is no longer a reviewer judgment item.

## Alternatives Considered

- **A new `boundary` gate kind** — rejected in the plan as high surface area for a review-shaped check.
- **Enforce at the `qa` stage** — rejected: the `qa` schema is test-count-shaped, and the changed-file set is final by review.
- **Prose-only lens strengthening** — rejected: ADR-008 already tried this and consumer defects proved it ineffective.
- **A standalone `aet check boundary` command** — rejected: whether it runs becomes reviewer recall again.
- **Extend the `review` SCHEMAS entry with a `lenses` key** — rejected: required schema keys invalidate every existing review payload.
