# Changelog

## [1.14.0] — 2026-09-09

### Added

- **An epic is declared once instead of inferred on every run** — `aet epic set <branch>` writes the active epic into the queue envelope. `aet epic show` reads it and `aet epic clear` removes it. The declaration carries the pull request title and a body file, so an epic pull request has somewhere to live before it ships. Intake stamps the branch onto the task record. A later run halts when the stamp and the active resolution disagree, and the error names the mismatch. `aet ship open-epic` runs the gate and opens the epic pull request. The integration branch now resolves through eight ordered steps, and each result names its provenance. Filename-stem derivation drops to a fallback (ADR-076).
- **`aet docs lint` checks three more classes of copied fact** — `adr_corpus_integrity` catches a duplicate ADR number, a dangling `supersedes:` or `relates:`, a relation naming a superseded record, and a missing `subject:`. `retired_path_absent` catches prose that still names a data path the toolkit retired. `code_anchor_resolves` refuses a `path.py:NN` line anchor and requires a symbol that resolves to a definition in the named file. A Python anchor resolves through the syntax tree, so a symbol surviving only in a comment is refused. `--severity warning` also reports the rules that have not yet ratcheted to error (ADR-074).
- **A deliberate divergence is declared rather than tolerated** — `<!-- aet-lint: off -->` and `<!-- aet-lint: on -->` exempt a span of a document. Both `aet docs lint` and `scripts/skills-lint` honour the markers. An unclosed `off` marker runs to the end of the document. `docs/CONVENTIONS.md` records the rule.
- **A run refuses in the foreground instead of dying detached** — `aet run` and `aet run-one` now check the circuit breaker, the queue, the agent binary and the worktree base before they detach. A failed check prints the reason and exits non-zero. The commands previously printed `🚀 Started run <id>` and exited 0 while the background child logged the refusal and stopped. The spawn also confirms the child is still alive before it returns (ADR-075).
- **`aet status` reports the circuit breaker and the health of the last run** — a tripped `refs/aet/breaker` shows as a banner. With no run active, status reads the newest telemetry record and names a previous run that ended in failure. Status previously reported tasks as `ready` and declared "No failed tasks" while the orchestrator was hard-blocked.
- **`aet breaker show` and `aet breaker reset`** — the circuit breaker is now inspected and cleared by command. Both accept `--repo-root`, and `show` accepts `--json`. Clearing it previously meant `git update-ref -d refs/aet/breaker`.
- **Plan files live in two directories** — `docs/plans/active/` holds drafts and in-flight plans and is ignored by default. `docs/plans/archive/` holds settled plans. `aet sprint add`, `aet backlog add`, `aet plan validate` and `aet plans lint` resolve both the partitioned and the legacy flat path. Closure archives the file when it is on disk and stays silent when it is not, so a worker that never held the file can still close a task (ADR-073).
- **`aet state audit` reports a task record carrying no plan spec** — it names each offender on stderr. The audit reconciled state against git before this and never checked specs.
- **`aet setup verify` prints the active epic** — the branch and its title appear beside the resolved trunk and integration branch.

### Fixed

- **A Claude Code session dispatched its work to Kimi** — adapter resolution ended in a `PATH` probe over a fixed dictionary, so being installed read as being preferred. Resolution now reads `--cli-bin`, then `AET_CLI_BIN`, then the calling agent, then it fails and names the flag. The calling agent is detected from the process ancestry, not from environment markers. Agent CLIs fork one another and inherit each other's markers, so a marker probe would recreate the bug. `aet run` and `aet run-one` resolve in session and always forward `--cli-bin`, because the detached orchestrator loses sight of the agent that started it. There is no longer any fallback to whatever happens to be installed.
- **Git waited on a prompt nobody could answer** — an SSH `origin` with no key loaded and no terminal blocked git on a passphrase or host-key prompt. It showed as a 180-second hang on `aet state transition` and `aet gate submit` inside an agent container, where the deadline that fired belonged to the harness. The CLI now sets `GIT_TERMINAL_PROMPT=0` always. It sets SSH batch mode only when stdin is not a terminal, because with a terminal attached there is somebody to answer. A configured `core.sshCommand` is read first and left intact, so a deploy key on a CI runner still works. Measured against an unroutable host, the failure takes 5.1 seconds instead of hanging.
- **The test suite read and wrote the developer's real state** — both orchestrator rehearsals ran a full batch in `setUpClass`, which pytest reaches before any function-scoped isolation is in effect. Every run therefore wrote into the real telemetry archive and provenance ledger. The evidence was 384 debris telemetry directories against 5 real projects, and 317 of 770 ledger lines describing tasks that never existed. A class-scoped autouse fixture now establishes the same redirections one scope earlier. Separately, `test_live_board_specs.py` asserted over this repository's live board, so a record left by an interrupted run failed the suite for every developer. That property is now asserted over a fixture with three divergent cases, and the standing check moved into `aet state audit`.
- **A branch sitting on its own base derived as `in_progress`** — `derive_status` read branch existence as activity. It now requires the task's own commits as evidence. A branch with no recorded session derives as an unstarted task (ADR-072).
- **A recycled PID reported a finished run as active** — one predicate now decides run liveness. A recorded returncode settles it. Otherwise the PID must be held by a process whose start time is not later than the run's recorded start. `aet status` had reported five runs from 2026-08-19 as active; two of those PIDs belonged to QuickLookUIService and chrome_crashpad_handler, both started days later. The run lease uses the same predicate, so a crashed run whose PID was recycled can no longer refuse every mutating queue command.
- **`aet ship merge` gated a tree it was not merging** — the gate, the conflict detection and the commit count now run against the resolved feature branch instead of the ambient checkout. The command can no longer report a passing gate about another tree. `aet ship split` was the last commit-count caller reading ambient `HEAD`. It resolves the branch, refuses when the checkout is not on it, and counts against it. Handing it the resolved branch alone was unsafe, because the `reset --soft` below it rewrites the checkout it runs in.
- **A placeholder satisfied a stage gate** — a verdict field that gates a stage is value-checked, not only type-checked. A well-formed payload carrying a placeholder `summary` is now refused.
- **Triage decided from the class label with no evidence** — with no stage, no signature and no tail, it falls through to the deterministic classifier default instead of answering.
- **A count of zero rendered like an unscanned bucket** — `aet mine-learnings` and `aet retro` distinguish the two. A field of ties is no longer presented as a field of firsts.
- **`make validate` could report `0 failed` while discounting a red** — known intermittent tests carry `xfail` and a tolerated-reds register, so the number means what it says.
- **`aet` could run installed code from inside a working tree** — the `main.py` entrypoint now puts the local `src` directory first.
- **`aet epic` was missing from the help index** — `epic` now appears under Plan work and `breaker` under Run work.
- **Two ADR records shared the number 072** — "ADR-072" stopped identifying one record, and an incident report cited the wrong one. The second record is renumbered 073. Every citation in the tree meant the proxy record, so only the index moved.
- **ADR-053 carried no frontmatter** — ADR-062 declares `supersedes: [53]`, so `aet context` printed a dangling-supersedes conflict at every session start. ADR-053 now resolves to a lineage. ADR-073's `relates` also points at ADR-055 rather than the superseded ADR-054.

### Changed

- **ADR frontmatter is required rather than optional** — 39 of 72 records carried none, and `unique_live_subject` skipped every one of them by explicit instruction in the evaluator. The rule guarding the corpus therefore read less than half of it. Frontmatter is backfilled across all 39 legacy records, and `adr_corpus_integrity` is ratcheted from warning to error. ADR-074 supersedes ADR-056 and carries its decisions forward with this one change.
- **Skill and document prose no longer names retired data paths** — around 50 references to `.agents/work-queue.json` and its siblings were swept. The `git-refs` backend stopped writing those paths.
- **PRD code anchors are re-anchored on symbol names** — 132 `path.py:NN` line anchors were rewritten. `aet-sync-docs` consumes them, and four of five anchors in one initiative had decayed to unrelated code by the time it closed.
- **The 38 settled plans left loose in `docs/plans/` are archived** — each landed at `docs/plans/archive/<task_id>.md` through the closure path. Settledness was read from the `refs/aet/sealed/*` tombstones and merge history. Four files were renamed to their task id first, because the filename kept a `-plan` suffix the frontmatter never had. The markdownlint pre-commit hook now excludes the archive, as `aet plans lint` already did. Restyling a frozen record to satisfy a linter would rewrite history.
- **A proxy is refusable at review** — ADR-072 records that a signal cheap to read may not stand in for the evidence a decision needs. Conformance is shown by constructing the divergent case, because a test that builds proxy and fact together cannot show them disagreeing.

### Documentation

- **ADR-072 (A Proxy Is Not Evidence)** generalises ADR-064 beyond the merge transition and names eight conformance sites. ADR-064 fixed one site and never stated its reasoning, so seven more instances of the same shape were each found independently over two months and read as isolated bugs. The `evidence-over-proxy` PRD carries the sites into the plans that closed them, and none of those plans adds a mechanism, a dependency or a stored artifact.
- **ADR-073, ADR-074, ADR-075 and ADR-076** record the partitioned plan layout, the document-conformance rule grammar, synchronous preflight and status truthfulness, and declared epic identity. The `partitioned-plan-directory-layout`, `document-conformance-lint` and `orchestrator-status-and-preflight-integrity` PRDs carry their scope.
- **The `aet-work` runtime self-detection PRD is marked superseded** — it specified adapter detection as an agent self-report, which is AI-remembered state and regressed. Detection is code-enforced now. The PRD is kept because it is the only surviving description of that work.
- A learning records a ship-merge bypass observed when the dirty-worktree gate failed.

**Upgrading from 1.13.x:** upgrade the skills alongside the CLI. Add `docs/plans/active/` to `.gitignore` and move draft plans into it; `aet setup bootstrap` writes the entry and `aet setup verify` reports it missing. Legacy `docs/plans/<id>.md` paths still resolve, so no plan has to move at once. `aet docs lint` gains three rules, and `adr_corpus_integrity` runs at error severity, so a repository with ADR records lacking frontmatter will fail the lint until they are backfilled. Adapter selection no longer falls back to `PATH`: a run started outside a recognised agent CLI needs `--cli-bin` or `AET_CLI_BIN`. Epic declaration is optional and config or filename-stem derivation still works.

---

## [1.13.0] — 2026-08-28

### Added

- **A queued plan can be corrected without touching shared state** — `aet sprint add` re-ingests the spec of a task that is still inert (`planned`, `ready` or `blocked`), so a plan invalidated by a sibling merging ahead of it is fixed by editing the file and re-adding. Previously the only route was deleting the task ref on `origin` and re-adding, which is an irreversible operation on state every other clone reads. A task carrying run state is refused by name rather than silently reshaped (ADR-068).
- **Board admission is one operation** — every door onto the board (`aet sprint add`, `aet sprint intake`, `aet backlog add`) runs the same admission policy from a single domain module, instead of each implementing its own. It was implemented once per door before, which is how a plan-footer read that three accepted decisions forbade survived all three (ADR-066).
- **A stage's evidence requirement comes from the workflow** — `aet ship` resolves which verdict a stage needs by reading the workflow definition rather than carrying its own list, and a gate's default routing derives from the plan's work class (ADR-067).
- **Divergence is recorded at closure** — the mechanical difference between what a plan described and what landed is written onto settled history when a task closes, so it survives without depending on a documentation stage having run.

### Fixed

- **A runaway requeue loop could not be stopped** — one task requeued 22 times against a single closed provider window at a recorded $23.77, and four independent stops were inert at once. Each is fixed: a throttle is recorded as a non-countable failure so the run can halt on it, the provider-limit wordings a harness actually emits are classified as throttles rather than as unknown faults, direct task-record writes replicate so a later fetch cannot discard them, and the loop miner counts a requeue loop from stage records instead of from prose (ADR-065 as amended, ADR-071).
- **A failed stage group discarded the stages it had proved** — a group session that died partway returned before recording anything, leaving the task at the group's entry stage no matter how many stages had finished. The retry was then prompted with a stage that contradicted its own worktree, and re-ran finished work. Stages backed by a passing verdict are now kept (ADR-069).
- **The verify gate could not be satisfied in the pipeline** — it read a working-tree markdown file that no producer writes, so the only way past it was out of band. It now reads the `verify` verdict that the verify stage itself writes (ADR-070).
- **A context digest under a symlinked repository root produced absolute paths** — the digest now relativises through the resolved root, so a checkout reached by a symlink yields the same digest as one reached directly.
- **Liveness supervision on Linux scanned indirectly** — the check now reads `/proc` directly rather than inferring liveness through a shell.
- **A trailing-slash check read markdown formatting as content** — backticks are stripped before the check, so a path written in code formatting is no longer misjudged.
- **`make install-skills` reported success without correcting a stale link** — the target tested only whether a symlink existed and printed `✓ already linked` whatever it pointed at, so a link made against an older checkout was never repointed and the drift was silent: the skill loads, nothing fails, and the session follows instructions from the other checkout. It now routes through `aet setup skills`, which reads each link's target, and runs this repository's own code rather than whichever `aet` is on `PATH` — a release install would otherwise relink from its own clone. `aet setup verify` reports any skill link that points elsewhere.
- **`aet ship` could not run without an `origin` remote** — the pre-merge gate fetches first and the fetch was unguarded, so on a repository with no remote every subcommand in the family — `gate`, `open`, `merge`, `split`, `close` — died before doing any work. The fetch is now skipped when no `origin` is configured, mirroring the guard the task store already applies for the same reason. A fetch that fails against a remote that does exist still fails loudly.

### Changed

- **Plan stage footers are no longer emitted or read at intake** — a plan's `*Stage:*` line is a human breadcrumb. The stage of record lives on the task record (ADR-061), and no admission path consults the footer. Existing footers are tolerated and ignored.

### Documentation

- **The skills documented a config key removed in 1.10** — `aet-work` and `aet-setup` still presented `task_backend` as a live setting with `git-refs` and `json` values, and `aet-setup` claimed its writer sets it by default, when `aet configure` rejects the flag and the JSON store no longer exists. Following the instructions produced a config the CLI refuses. Fifteen references across eight files now state that `git-refs` is the only task store and that the key was removed.
- **The bug, retro, audit, product-brief and report corpora were retired** — `docs/bugs/`, `docs/retros/`, `docs/audits/`, `docs/product-briefs/`, `reports/` and the root-level `aet-toolkit-defects.md` were removed after every document in them was verified against the tree. Nine of the thirteen defects in `aet-toolkit-defects.md` were already fixed, five of them while still marked open, and all four it described as patched only in an installed tree were upstream. `docs/CONVENTIONS.md` records that citations to those paths resolve in git history, and distinguishes them from `~/.aet/reports/`, the live verdict archive.

**Upgrading from 1.12.x:** upgrade the skills alongside the CLI. `aet ship gate` now requires a passing `verify` verdict for any stage whose workflow declares one, and the `aet-verify` skill that writes it gained that step in this release — so a CLI upgraded past a skill set from 1.12 or earlier can refuse work at ship that a matching pair would pass. `npx skills add ... --all` (or `aet setup skills` from a working tree) brings them level. Plans already on the board are unaffected, and plan footers already written are ignored rather than rejected.

---

## [1.12.0] — 2026-08-27

### Added

- **Antigravity (`agy`) is a supported agent CLI** — a third adapter alongside `claude` and `kimi`, with its own session-log and transcript extraction so runs driven by it produce the same telemetry, usage figures, and session traceability as the others. Model and reasoning effort are selectable per session through `AET_AGY_MODEL` and `AET_AGY_EFFORT`.

### Fixed

- **`aet report` counted nothing** — the archive scan matched only `*.jsonl` and never read the run summary in `last-run.json`, so every archive-wide report showed `Runs: 0` and zero tasks, cost, and wall-clock time while `Runs observed` counted the run. The tell was the two numbers disagreeing; the cause was one reader not following the archive layout its own writer and two other readers already used.
- **Every task that did any work stranded its worktree** — teardown refused whenever the branch had commits, which is true of every task that succeeded. Committed work lives on the branch ref and survives removal, so teardown now blocks only on uncommitted changes. The refresh path, which rebuilds a branch from its base, still refuses on committed work.
- **`aet sprint intake` admitted plans without checking them** — the GitHub-issue door onto the board ran no validation at all, so a plan reachable from an `aet:sprint` issue was queued without its frontmatter contract, requirement citations, or coverage ever being checked, while the identical plan was refused by `aet sprint add`. Both doors now apply the same admission policy.
- **`agy` sessions were killed at five minutes** — the CLI's own `--print-timeout` defaults to `5m0s` and was never set, so stage sessions were aborted at roughly 300 seconds regardless of the toolkit's own two-hour supervision ceiling. It is now derived from that ceiling rather than left to the CLI's default.
- **An aborted `agy` session lost all of its work** — buffered output is printed only on completion, so a session that ran out of time returned nothing at all. Output is now streamed, leaving partial work behind and making progress visible while a stage runs.
- **A CLI deadline was recorded as a flake** — a session killed by the agent CLI's own timeout is now classified as a timeout, so a run's telemetry no longer describes a deterministic limit as a transient fault.
- **A refusal that could not be satisfied now says so** — when a plan cites a requirement it is itself introducing, intake explains that the check compares citations against requirements that already exist and points at the acknowledgement line, instead of reporting the requirement as unknown and inviting a fix that makes the plan wrong.

### Changed

- **`aet-plan`'s completion protocol agrees with the code again** — two instructions contradicted what intake enforces: one forbade the plan stage footer that `aet sprint add` requires, and another asked the agent to confirm an intake step a different instruction forbids it from taking, against a queue path the backend no longer writes. Intake is now stated to belong to the operator or to `aet-pipeline-plan`.

### Documentation

- **ADR-066 (Board Admission Has One Path)** and the `single-admission-path` PRD record why board admission is being consolidated into a single operation: it is implemented once per door today, which is how a plan-footer read forbidden by three accepted decisions survived all three.
- Bug reports filed for the defects found alongside this release — worktree teardown, the report archive scan, the unsatisfiable requirement refusal, the ship gate reading the ambient checkout, the `agy` timeout, and `aet state reset` deriving `merged` from a branch with no commits.
- An idea document records the open question of whether per-branch quality verdicts compose across a parallel batch.

---

## [1.11.0] — 2026-08-24

### Added

- **Intake validation applies at every door** — `aet run-one` now runs the same check suite `aet sprint add` enforces, over the same plan corpus and with the same `⚠️ VALIDATE ACK` escape hatch, and refuses a plan that fails it. `--skip-intake` runs anyway and records the bypassed check ids on the task record, so the audit trail can answer whether a task passed intake. A batch child is not re-judged; its task passed on the way in (OI-06).
- **A `throttled` failure class** — a provider rate limit, quota, or session limit is classified on its own terms instead of as a flake. The task is requeued, the shift stops spawning, and no triage session is spent: the limit is shared, so the next task would meet the same wall. Throttles are not circuit-breaker evidence, so a task is never quarantined for a closed window (OI-07, ADR-065).
- **R-trace coverage read from the task record** — a requirement stays covered once any plan sharing the PRD delivers it, and settled siblings live in the record rather than in `docs/plans/`. `aet plan validate` and `aet sprint add` now credit them, so a plan whose siblings have all merged is no longer asked to trace requirements they already covered. Records carrying no spec are named rather than skipped (OI-05).
- **`aet setup verify` reports `.gitignore` drift** — both an entry the toolkit writes that the file lacks, and a retired name it still carries. Reporting is limited to names the toolkit itself once wrote, so a project's own entries are never flagged (OI-02).

### Changed

- **Test selection is derived from the source, not a table** — `make validate` and `aet-implement` now share one mechanism, which reads which test files reference which modules (imports, plus the quoted-path idiom used to load CLI modules) and follows those references transitively. The hand-maintained path table is gone. No selected target names a file that does not exist, a source file that no test reaches has to be acknowledged explicitly rather than silently widening the run, and a change reaching most of the suite is reported as the full suite (OI-09).
- **`aet plan validate` states what it checked** — the result names the number of plans validated and which sources decided r-trace coverage, so a single-file run is no longer indistinguishable in form from a whole-corpus one. Failures add a finding count and the ack syntax that resolves them (OI-13).
- **`aet plan validate` accepts a directory** — `docs/plans/` expands to its `*.md` children instead of raising (OI-14).
- **The intake refusal names the override** — `aet sprint add` prints the `⚠️ VALIDATE ACK: <check-id> — <reason>` syntax at the point of refusal, rather than leaving it documented only in module docstrings (OI-01).
- **Integration branches derive from the PRD** — in `single-pr` mode a task's integration branch comes from the PRD it belongs to, so concurrent PRDs each carry their own branch and PR. Explicit CLI and environment overrides still win, and `pr-per-task` is unchanged (owb-13, R-17).

### Fixed

- **`aet state audit` no longer aborts with a traceback** — a config carrying the removed `task_backend` key, or only the legacy `.agents/aet-work.json`, is refused by name with the migration it needs. Read-only commands were exiting 1 with a full Rich traceback that buried the remedy (OI-12).
- **`aet plan validate` with no arguments validated nothing** — the repository root resolved to the parent of the checkout, so the documented default invocation found no plans and reported success. It now resolves the repository it runs in (OI-14).
- **Verdicts attest to the tree the work is in** — `aet gate submit` stamped its tree fingerprint from the main checkout while the freshness check hashed the worktree, so the two compared different trees. Both now use the worktree (OI-04).
- **The test suite no longer reaches the real repository's remote** — tests running backend code under a cleared environment resolved this checkout and fetched `refs/aet/*` with a forced refspec, which on a machine whose git auth survived would overwrite local refs from origin. A full run now leaves `.git/FETCH_HEAD` untouched (OI-03).
- **Backend construction no longer re-derives a root it was given** — `create_backend` computes the repository root in pure Python and now passes it through, instead of spending a `git rev-parse` per construction to recompute it (OI-11).
- **Pre-commit `ruff` lints what is staged** — it ran over the whole repository on every commit, so an error in an untouched file could block an unrelated commit (OI-16).

### Documentation

- ADR-065 (throttling is not a flake) records the taxonomy change; the open-items register at `docs/audits/2026-08-24-open-items.md` carries all nineteen closures with the evidence for each.
- Three bug writeups and three learnings entries discarded in a local `main` reset are restored, and the divergence record notes that its preserved branches have since been deleted (OI-15, OI-19).
- The nightshift stall-timeout flake is filed with a measurement that could not reproduce it, three candidate mechanisms, and what to capture if it recurs (OI-17).

---

## [1.10.0] — 2026-08-23

### Removed

- **The JSON task backend is gone** — `git-refs` is now the only task store. The `task_backend` config key is rejected with a migration message, and the backend selection axis has been collapsed entirely (owb-07).
- **`aet init-queue` is gone** — the board is derived from open work rather than rebuilt by scanning `docs/plans/`. `aet queue sync` now reconciles the existing live queue only; it no longer scans or validates plan files (owb-05).
- **The plan archive is retired** — `docs/plans/archive/` and its 264 files are removed, along with `queue.archive_plan_file` and the `plans_archive_dir` telemetry path. Terminal closure no longer moves plan files anywhere (trp-05, ADR-055 decision 4).
- **`aet ship` no longer accepts plan paths** — all five ship entry points resolve a task id against the record. Passing a `.md` path is rejected with a message naming `aet sprint add` (trp-02, R-3).

### Added

- **Sprint intake from GitHub labels** — `aet sprint intake` reads `aet:sprint` issues, validates each candidate against the dependency graph, and admits it or refuses with the blocking reason named. Forge reads retry with backoff and then fail closed (owb-10, ADR-032/033).
- **Tombstones replace absence** — sealing a task writes `refs/aet/sealed/<id>` in the same atomic transaction as the task-ref deletion, so clones converge by reading and a task that vanished is distinguishable from one that never existed. `aet state reconcile` reports and removes refs stranded by the old model (dia-01, dia-02, ADR-059).
- **Shadow posture** — projects with no in-tree config keep their board entirely local: nothing is pushed, projections are suppressed, and the inferred posture is announced once per run (owb-11).
- **Stage-based validation** — implement runs a targeted test set selected from the changed paths and hands the result to QA, which always runs the full suite. A single-run file-hash cache skips redundant re-validation within a run, and a failed QA compares its failures against the implement set to attach a gap analysis to the task's failure record (validation-01, validation-02, validation-03).
- **Hybrid liveness supervision** — process-tree and run-log liveness replace the stdout-silence watchdog, so a quiet-but-working session is no longer killed. Adapter stall and wall-clock timeouts are uniform at 7200s (liveness-01).
- **A single-hop command index** — `aet --help` renders every command in one flat, sectioned index with required arguments inline, instead of forcing a second call to discover subcommands. Missing-argument and unknown-command errors now append a runnable example (cdc-01, cdc-02).
- **`aet state backfill-specs`** — recovers a task's plan spec from a git revision that still has it, for records created before the spec moved into the task record (owb-15, R-19).
- **Config schema validation** — unknown keys are rejected with legal alternatives named, projections are refused in shadow sources, and `aet configure --shared` declares a config as shared across devices (owb-12).
- **Computable plan-size floor signals** — file-set overlap with a linearly-ordered sibling, and docs-only with a single sibling consumer, reported as lint warnings under a 2-of-N trigger (gdl-01).

### Changed

- **Plan files are transient working copies** — nothing writes back to them. Stage lives on the queue and ledger; every skill that told a worker to update or commit a `*Stage:*` footer has been rewritten. PRD footers are unaffected (R-4/R-19).
- **Signal death is authoritative for timeout classification** — any negative exit code classifies as `timeout` at all three call sites, and a signal exit is treated as evidence of timeout even when the child could not record one (osd-02, ADR-060).
- **The settled-plan archive is machine-local** rather than tracked (owb-03), and the ledger path is derived in one place instead of three (owb-08).

### Fixed

- **Proxy signals were being read as evidence** — ancestry was treated as proof of merge, absence as proof of completion, and a nonzero exit as proof of failed work. Merge now requires a recorded `merge_commit` or movement past a recorded `base_commit`; leases refuse to overwrite a live holder; blocker satisfaction requires positive evidence. `aet state heal --apply` could previously seal a zero-commit task as merged with a merge commit it invented (ADR-064).
- **Settled tasks were invisible in the default posture** — `seal` writes the settled record to two places but only the tombstone unconditionally, and the resolver read only the JSONL. Re-running a closure reported "Task not found" for a task that had settled successfully, breaking R-4 idempotency.
- **An idle run held the queue lease for 8+ hours** — `has_actionable_tasks` counted any stored `in_progress` task as actionable, so a task left behind by a dead run kept the exit condition from firing. Ownership, not stored state, now distinguishes a live worker from a dead one.
- **Queue bookkeeping degraded into silent data loss** — programming errors in `_record_run_one_in_queue` surfaced as a single warning while metadata recording stopped. Those now propagate; environmental failures still warn without blocking the run.
- **Failure triage misclassified design defects as environmental** — bare `missing`, `not found`, `dependency`, and `cannot find` patterns matched almost any log tail and leaned toward requeue instead of triage.
- **Worktree teardown failures were silent** (osd-03), **git-refs runtime metadata did not replicate to origin** (4409f891), and **ledger repo-root discovery failed quietly on a nonexistent path** (8e2b160c).

### Documentation

- ADR-059 (absence is not a fact), ADR-060 (signal death is timeout), and ADR-064 (merge evidence) record the decisions behind this release.
- Skills now state the phase model explicitly (trp-06) and describe what the code actually does rather than what it once did (owb-14).
- A docs-lint guard rejects hand-copied CLI option tables, which drift from the real `--help` output (cdc-03).

---

## [1.9.0] — 2026-08-15

### Added

- **Plan spec travels in the task record** — `new_task_from_plan` embeds a portable spec (routing frontmatter, title, body, task list) so a plan authored on one machine reaches another through the queue. The orchestrator renders the working plan into the worktree at task start (owb-01).
- **Register every file AET writes under `.agents/`** — `AET_IGNORED_PATHS` and `AET_TOLERATED_DIRTY_PATHS` now explicitly declare which toolkit-written paths are never-tracked vs. tolerated-dirty, halting adoption projects where an unregistered path breaks base hygiene (sst-01).
- **Recover missing stage verdicts** — the orchestrator now runs one narrow recovery session when a verdict file is missing, instead of discarding and re-running the entire stage. Invalid and fail verdicts are never retried (orchestrator).

### Changed

- **git-refs is the tracked task backend** — `.agents/aet-config.json` selects `git-refs` by default so the board lives in `refs/aet/*` and travels with the repository instead of a gitignored `work-queue.json` (ADR-055 decision 4).
- **Config and store anchored to the same repository** — backend creation and config resolution now derive the repository root from the queue file path once, preventing a project config in one tree from governing a store in another.

### Fixed

- **git-refs state replication** — `aet-state transition` now pushes task refs to origin, and both `save()` and `seal()` push explicit deletion refspecs for pruned task refs so sealed tasks do not resurrect as live work on other clones.
- **Claude transcript reader** — fixed slug generation for `.worktrees/` and dotted usernames, piped test commands, and the real record shape so session logs produce test-run records.
- **Ledger integrity** — the ledger now verifies content addresses on load and appends events instead of rewriting the file, preventing malformed lines or transient read failures from silently truncating the store.
- **Orchestrator group prompt** — removed the contradiction between the group preamble (run all stages) and per-stage blocks (run only this stage), which had caused group sessions to stop after stage one.
- **Verdict submission documentation** — `aet gate submit` builder mode is now single-sourced and documented in `aet-qa`, `aet-review`, `aet-cso`, and `aet-verify` skills, replacing hand-authored `--evidence` JSON.

### Documentation

- Added bug reports for git-refs stale refs and config/store anchoring defects.
- Added PRDs and plans for the open-work-board and plan-floor-guardrail programmes.
- Updated `CONTEXT.md` glossary to describe the actual roles of the provenance ledger, execution log, and work queue.

---

## [1.8.0] — 2026-08-12

### Added

- **`aet learnings append`** — new CLI command for append-only JSONL learnings with schema validation and integration tests (t2r-01).
- **`aet context`** — top-level context command that collects git and filesystem state, reads canonical plan stages, supports TARGET pinning, budgets, PRIME.md override, `--memories-only`, and `--hook-json` SessionStart envelopes (t2r-04).
- **`aet handoff`** — run-scoped handoff note command with `append` and `show` subcommands; the orchestrator injects handoff clauses into stage prompts so agents can pass context between sessions (t2r-10).
- **`aet docs generate`** — deterministic tree-walk generator that regenerates `docs/CLI.md` from the Typer command tree, with a drift guard to keep the reference current and machine-independent (t2r-11).
- **Plan archival at terminal closure** — settled plans are automatically moved to `docs/plans/archive/` when a task reaches `merged` or `abandoned`; closure also force-adds gitignored live plans so archival commits succeed (t2r-12, ADR-054).
- **Identity-conflation lens** — mechanical gate-review lens that blocks commits mixing identifier namespaces; wired into `aet gate submit --stage review` (t2r-09).
- **Boundary-contract lens** — mechanical gate-review lens that enforces path-level boundary contracts and agreement tests; wired into `aet gate submit --stage review` with ADR-057 recording the carrier decision (t2r-08).
- **Single-PR rehearsal** — end-to-end rehearsal fixture with shadow-layer config and real `npm ci`, validating post-rebase behavior and that only the epic branch is pushed (t2r-13).
- **Skills preamble absorption** — shared skill preambles and banners are absorbed into `aet context` instead of duplicated in every skill prompt (t2r-05).
- **ADR frontmatter docs lint** — `aet docs lint` gains the `unique_live_subject` rule and directory-target support for `must_contain`/`must_not_contain`; ADR-056 documents the frontmatter contract (t2r-06).
- **Content-addressed ledger events** — queue stage and verdict events are written to an append-only, content-addressed ledger with commutative envelope semantics; skills warn against hand-editing the ledger (slc-01).
- **git-refs sync across command boundaries** — `TaskBackend.fetch()`/`push()` for `refs/aet/*` is invoked after sprint add, set-stage, gate submit, and ship close, enabling multi-machine workflows without leaking local `~/.aet` state (slc-02).
- **Mechanical closure transaction** — `aet ship` batches git-refs backend updates in a single `update-ref --stdin` transaction and routes terminal transitions through one code path (slc-04).
- **Atomic set-stage footer and gate submit builders** — `aet state set-stage` updates the plan footer atomically with the queue stage write and clears stale `failure_reason`; `aet gate submit` builds verdict payloads from `--from-pytest`, `--summary`, and `--divergence` when `--evidence` is omitted (slc-05).
- **Current-rules digest and durable insights** — `aet context` includes a current-rules digest from ADR frontmatter and top-N recent learnings from `.agents/learnings.jsonl` (t2r-07).

### Changed

- **`aet ship verify --squash-fallback` and `aet ship close --delete-branch`** — drift-tolerant diff fallback for squash merges, an explicit `verify` command with `EXIT_VERIFY_NO_MATCH` / `EXIT_VERIFY_AMBIGUOUS` exits, and optional branch deletion on close (t2r-02).
- **Stacked PR split and trunk substitution** — `aet ship split` resets soft and groups commits; trunk resolves via `branch_ref.py`; stack info is injected into the PR body; a stacked merge guard blocks risky merges; and a `cut/pr` ledger event records stacked PR opens (t2r-03).
- **Plan status authority removed** — settled-ness now derives from settled history, git ancestry, and the terminal footer instead of plan frontmatter `status`; `aet backlog add` guards against sprint members and settled history (slc-03).

### Fixed

- **Worktree base without remote** — `resolve_base_ref()` now prefers the remote-tracking ref, leaves already-qualified refs alone, and falls back to the local branch so repos without `origin` or unpushed integration branches no longer fail at `git worktree add`.
- **Claude stall timeout** — raised to the wall backstop so healthy `json-envelope` sessions are not killed after 30 minutes of silence.
- **Machine-independent generated CLI reference** — default option rendering collapses `Path.home()` to `~`, so `docs/CLI.md` no longer embeds one contributor's home directory (t2r-11).
- **Ignored live plan staging** — `git add -f` is used for gitignored live plans during closure and seeding, with environment failure signatures recorded when seeding fails (t2r-12).
- **False identity lens stems** — escaped newlines no longer produce false stems in the identity-conflation lens (t2r-09).
- **Stage verdict prompts** — orchestrator prompts explicitly require agents to submit the required verdict via `aet gate submit` and state that the stage is not complete until the verdict is written.
- **Ledger hand-edit warning** — `aet-work` and `aet-ship` skill instructions warn that `.agents/ledger.jsonl` is append-only and content-addressed.
- **Internal link checks** — `validate-skills.sh` skips `node_modules` and excludes `docs/plans/archive/` from internal link checks.

### Documentation

- Added ADR-055 (provenance ledger / single-ledger closure), ADR-056 (ADR frontmatter contract), and ADR-057 (boundary-contract lens carrier decision).
- Added PRDs and plans for the t2r-01..t2r-13 and slc-01..slc-06 improvement sprints.
- Updated `CONTEXT.md`, `docs/CONVENTIONS.md`, `docs/PIPELINE.md`, and `docs/WORKFLOW-github.md` for ADR-055 multi-machine posture, provenance ledger terminology, and plan archival layout.

---

## [1.7.0] — 2026-08-07

### Added

- **Local-only plans** — `docs/plans/*.md` files are no longer committed or pushed at intake. A plan flows from `aet sprint add` through implementation and lands in its task branch's PR diff; terminal status is still written durably at merge closure (lop-01, lop-02, lop-03, ADR-054).
- **Plan overlay snapshot** — the orchestrator copies the current working-tree version of a task's plan into its worktree regardless of git state, so mid-sprint plan edits take effect without a publish step (lop-02).
- **Task-branch plan seeding** — the first commit on a task branch adds only that task's own plan file, keeping PR diffs focused (lop-02).

### Fixed

- **Closure fails closed on missing plan** — `aet ship close` and the sealed-task retry path now refuse silently when a plan file cannot be resolved from the checkout or merged branch, and report the recovery path (lop-03).

### Documentation

- Added ADR-054 covering plan documents outside the durability gate.
- Updated planning skills and `aet-work` references to remove the obsolete "commit plans before queueing" instruction and document the `git clean` hazard for untracked plans.

---

## [1.6.0] — 2026-07-29

### Added

- **Deterministic `aet run` / `aet run-one` invocation** — execution is now detached-only; removed `--foreground`, `--max-jobs`, `--isolation`, and `--stall-timeout` from the CLI surface and applied sensible defaults internally. The follower returns a bounded completion report instead of streaming logs (rid-01..rid-06).
- **Non-streaming terminal follower** — `aet run-one` and `aet run --follow` wait for a structured, bounded completion report rather than tailing a live log (rid-03, rid-04).
- **Per-adapter supervision defaults** — `CLIAdapter` carries `stall_timeout` and `wall_backstop` defaults, so watchdog behavior resolves from the active adapter instead of CLI flags (rid-05, ADR-053).
- **Shared plan-argument resolver** — `aet ship`, `sprint`, `backlog`, and `run-one` share `resolve_plan_arg`, so bare task IDs and plan paths resolve consistently across commands (rid-02).
- **Adapter-dispatched session-log readers** — telemetry now reads Kimi wire logs and Claude Code transcripts through a shared dispatch seam, capturing test invocations from both agent CLIs (tap-03, ADR-050).
- **Test-run provenance** — every `test_run` record carries a required `source` (`wire`, `verdict`, or `unknown`), and the panel, desk, and `mine-learnings` split observed and claimed aggregates instead of blending them (tap-05, ADR-051).
- **Traceable stage records** — stage records include a `session_identifier` resolved by the adapter, so a stage can be traced back to the session log that produced it (tap-04, ADR-031).
- **Targeted validation scope observability** — `make validate` emits a machine-readable scope marker; the orchestrator classifies test runs as `full-suite` or `impact` from actual command output (tap-06, ADR-049).
- **Size column in `aet status`** — status output shows each task's declared S/M/L size from plan frontmatter.
- **Guided setup flow** — `aet configure --guided` offers an interactive two-question flow for scope and integration mode, with non-interactive bypasses for unattended runs (cfg-04).

### Changed

- **Simpler run CLI surface** — `aet run` and `aet run-one` no longer expose concurrency, isolation, or stall tuning flags; defaults are enforced internally.
- **Test scope classification now reads command output** — previously a string heuristic; for `make` it now uses the resolved-targets marker produced by `change_scope --explain`.
- **Configuration documentation and upgrade guide** — consolidated config docs, updated skill references for `aet-config.json`, and added `docs/upgrades/v1.5.0-to-v1.6.0.md` (cfg-05).

### Fixed

- **Plan intake status/stage consistency** — `aet plan validate` now rejects plans whose frontmatter `status` and footer `_Stage:` disagree, preventing stages from being skipped.
- **`aet ship merge` source resolution** — resolves the merge source from the task ID rather than the current checkout.
- **Panel provenance tooltips** — `Th` now forwards props so the "Tests (claimed)" column header tooltip renders.
- **Session reference path vs identifier** — `CLIAdapter.resolve_session_ref` returns a session-id string for both Claude and Kimi, deferring path resolution to extraction time and guarding against symlinked worktrees resolving to null.
- **Targeted validation marker agreement** — multiple scope markers in output must now agree; disagreement falls back to full-suite to avoid misclassifying failing scoped runs.
- **Nightshift stall timeout** — raised to avoid flaky process-group kills under load (vre-03).

### Documentation

- Added ADR-049, ADR-050, ADR-051, ADR-052, and ADR-053 covering test-run scope observability, session-log adapter extension points, test-run provenance, factory metrics, and per-adapter supervision defaults.
- Added PRDs and plans for run-invocation determinism and telemetry adapter parity.
- Updated telemetry guide, run command docs, and skill references for detached execution and adapter-resolved session references.

---

## [1.5.0] — 2026-07-24

### Added

- **Configurable branch model** — `trunk_branch`, `integration_branch`, and `integration_mode` are resolved from config, environment, or CLI instead of hardcoding `main`; `aet setup verify` reports the resolved trunk and its provenance (epi-01, epi-02, epi-07, epi-11).
- **Single-PR integration mode** — new `integration_mode: single-pr` squashes task branches into a shared integration branch instead of opening one PR per task, with serialized integration behind an advisory lock and re-validation after rebase (epi-07…epi-10).
- **`aet ship merge` direct merge command** — merge a task branch directly into a target branch with pre-merge conflict detection via `git merge-tree`; `--branch` now defaults to `main` (aet-ship).
- **`aet ship open/gate/close` bare task IDs** — commands that previously required a plan path now accept a bare task id and resolve it to `docs/plans/<id>.md` automatically.
- **`aet size report` and `aet size backfill`** — aggregate and backfill delivered diff-size measurements for closed plans to calibrate future sizing estimates (psr-03).
- **Orchestrator run preconditions** — `aet setup bootstrap` adds required `.gitignore` entries and the orchestrator halts cleanly with `MissingPlanError` when a queued plan file is missing (epi-04).
- **Stage telemetry schema v2** — records `actual_stages`, `failure_class`, `plan_snapshot`, and per-task attempt counters for richer run analysis (ppt-04).

### Changed

- **Branch-aware worktree refresh** — refreshing a worktree no longer checks out the integration branch in the operator's repo root; all rebase operations happen inside isolated worktrees so HEAD stays unchanged (epi-03).
- **Scoped `init-queue` validation** — only plans actually being included in the sprint are validated; invalid plans outside the included set are warned and skipped instead of failing intake (epi-05).
- **Sizing model recalibration** — plan size is now measured at closure rather than gated at intake; S/M/L bands updated to S≤150, M≤600, L>600 lines with advisory 2-of-N checks (psr-01, ADR-046).
- **`aet status` compact empty states** — empty queues, zero-count task states, and healthy worktrees are summarized in single sentences instead of blank tables.
- **One console-script entry point** — `aet install` moved to `aet setup link` and targets the console script, eliminating broken self-repair paths and worktree-hijacked symlinks (fic-01, fic-02).

### Fixed

- **`aet ship` PR base detection** — branches merely behind `origin/main` no longer return their own name as the PR base; stacked branches still resolve to their parent feature branch.
- **`aet ship close` identifier handling** — accepts either a plan path or a bare task id and derives the missing identifier automatically.
- **State heal gap** — `aet state heal` now detects when a recorded branch no longer exists and clears stale branch/worktree fields; new `aet state reset` recomputes and un-starts a single task (epi-06).
- **`aet-validate-scope` closure check** — removed a deadlocked queue-membership guard that could block legitimate scope validation.
- **`aet queue sync` help text** — corrected the command description in CLI help output.

### Documentation

- Added ADR-044, ADR-045, ADR-046, ADR-047, and PRDs covering non-trunk integration, pipeline performance & telemetry, and plan-size measurement.
- Added bug reports and retrospective notes for `aet-ship` pr-base and close-UX issues.

---

## [1.4.0] — 2026-07-21

### Added

- **`aet setup skills`** — install skill symlinks into detected agent directories (`claude-code`, `kimi`, `cursor`, `generic`) with `--agent`, `--skills-dir`, `--bin-dir`, `--dry-run`, and `--force` flags (uvi-01).
- **One-line curl installer** — `scripts/install.sh` bootstraps `uv`, clones the repo, installs the `aet` CLI into a dedicated venv, and links skills into the agent directory; supports `--repo`, `--tag`, `--agent`, `--bin-dir`, `--skills-dir`, and `--dry-run` (uvi-02).
- **Installer smoke tests** — hermetic pytest suite exercises the installer against a local checkout and asserts `aet --version`, skill symlinks, idempotence, and `--dry-run` no-op behavior (uvi-03).
- **`make test-installer`** — standalone target that runs the installer smoke tests in isolation.

### Changed

- **README Quick Start rewrite** — leads with the curl one-liner, documents installer flags, adds tag-install and PATH-troubleshooting examples, and notes the `npx skills add` path (uvi-04).
- **Task-size guardrails revision** — replaces the dual file-count/task-list-line intake model with context-budget + subsystem-coherence rules; redefines L-size as a re-evaluation trigger rather than an automatic split (tgr-01/02).

### Fixed

- **`aet ship` branch push** — pushes the current branch explicitly as `HEAD:<branch>` so worktree branches are not rejected.
- **`aet ship` PR base normalization** — normalizes `origin/main` to `main` when invoking `gh pr create --base`.

## [1.3.0] — 2026-07-21

### Added

- **Unified `aet` CLI on Typer** — replaces the argparse multicall dispatcher with a single Typer app; subcommands register as noun-scoped groups; applies ADR-039 renames (pkg-11).
- **`aet ship` promoted to code** — `aet ship gate`, `aet ship open`, and `aet ship close` replace the legacy bare ship binary and skill-only workflow (nc-03a/b/c).
- **`aet docs lint`** — declarative rule engine for documentation invariants, backed by `.agents/doc-rules.yaml` (pld-02).
- **`aet plans lint`** — corpus classifier that validates the plans directory against structure and liveness rules (pld-04).
- **Prose assertions as data** — repo-level prose invariants moved from Python tests into declarative `doc-rules.yaml` rules (pld-03).
- **Prose-only validate fast path** — `make validate` skips the full pytest suite when the change set is documentation-only, running only doc-coupled tests (pld-05).

### Changed

- **Skills moved to `skills/`** — all skills now live under `skills/` as pure content; no-code rule enforced by `validate-skills.sh` (pkg-08).
- **Panel server on Starlette/uvicorn** — replaces stdlib `http.server` with a framework-backed server while preserving routes and behavior (pkg-12).

### Documentation

- Added ADR-040: documentation invariants are data (pld-01).
- Updated command references and skill docs for the Typer-based CLI.

## [1.2.0] — 2026-07-17

### Added

- **Night-shift runtime resilience suite** — Phase 5 adds per-task and systemic circuit breakers, a stall watchdog on event silence, failure-taxonomy classification, `--on-failure=triage` requeue/quarantine routing, a quarantined task state, and per-task cost rollup to the ledger (nsr-01…07).
- **Phase 5 exit-gate rehearsal** — end-to-end unattended rehearsal that injects failure and stall scenarios and verifies the orchestrator routes them correctly (nsr-07).
- **`aet plan validate` four-family check suite** — validate plans against structure, scope, dependency, and traceability rules from the CLI (twe-04).
- **Intake fail-closed gates** — `aet add`, `init-queue`, and `sync` now run the plan-validate suite and reject malformed plans at intake (twe-05).
- **Zero-review mechanism** — optional auto-merge eligibility based on track-record, with `desk --eligibility`, policy configuration, and an orchestrator hook; off by default (twe-06).
- **`aet desk` risk-ranked awaiting-merge view** — sort tasks by risk and bundle merge evidence for easier ship decisions (twe-02).
- **`aet desk` actions** — merge and abandon tasks directly from the desk TUI (twe-03).
- **Per-provider merge-guard harness** — detect provider-specific merge guards and adapt ship behavior, starting with a Claude adapter (twe-09).
- **Work-class plan attribute** — plans now record `work_class` and intake validates it, enabling richer routing and risk scoring (twe-01).
- **Phase 4 exit-gate rehearsal** — end-to-end rehearsal with an audit doc capturing the unattended run evidence (twe-07).
- **Autonomous-merge governance** — documented fail-closed governance and ship merge-neutral hygiene for future auto-merge paths (twe-08).

### Changed

- **Validation-freshness guard** — `aet gate submit` now stamps `tree_hash` before validating the submit payload, preventing stale verdicts from being accepted.
- **Worktree-aware install tests** — `aet install` tests now pass when invoked from inside a git worktree.

### Documentation

- Added Phase 4 and Phase 5 plan sets and PRDs (twe-01..09, nsr-01..07).
- Synced multiple plans to implementation reality after closure.

---

## [1.1.0] — 2026-07-15

### Added

- **Live-run panel** — `aet-work` exposes live-run visibility with a dirs API, honest status, and a panel that auto-refreshes every 5 seconds with incremental dir merging and tab-visibility-aware polling (lvp-01/02).
- **Usage-cost telemetry** — parses kimi wire files and captures agent CLI usage into the telemetry archive, with a cost view in the telemetry panel (uct-01).
- **`aet gate submit` verdict writer** — record skill verdicts directly from the CLI so the orchestrator can gate completion on structured evidence (ewl-01).
- **Pre-push hook gate** — `aet-setup` can install and check a pre-push gate that blocks pushes until skill verdicts pass (ewl-03).
- **git-refs as default written backend** — `aet-work` now writes queue state to git refs by default, with backend sealing and a parity suite (ewl-04).
- **git-refs tamper-evidence** — git-refs backend gains tamper-evident mutations for trustworthy unattended state (ewl-05).
- **Non-invasive external config root** — support an external config root without invasive repository changes (ewl-07).
- **Validation freshness primitive** — verdicts carry a `tree_hash` and a validation-freshness query so stale evidence can be detected (pfe-01).
- **QA-freshness clause injection** — orchestrator stage prompts now inject QA-freshness requirements into each stage (pfe-02).
- **Wire-log test-run extraction** — extract structured `test_run` records from wire logs for richer telemetry (ttf-01).
- **Verdict-derived test_run scope classification** — classify `test_run` scope from verdicts with honest nulls when evidence is missing (ttf-02).
- **Structural pattern mining** — `mine-learnings` and `aet-retro` can surface recurring structural patterns across projects (ttf-03).

### Changed

- **Slimmer scaffolded gates** — `aet-setup` no longer scaffolds Prettier into the default gate set (vgr-05).
- **Faster test suite** — pytest suite is now parallelized with `pytest-xdist` (vgr-04).
- **Slim markdown quality gates** — `make validate` uses lighter markdown gates and fails fast on the first problem (vgr-01).
- **Status command readability** — `aet-work status` renders the task list as a markdown table, shows only pending blockers, and prints a dependency table.

### Fixed

- **Global `aet` symlink safety** — worktree copies no longer hijack the global `aet` symlink (#116).
- **Untracked plan intake** — `aet-work` refuses untracked plans at `aet add` instead of silently accepting them.
- **Telemetry reader alignment** — `aet-retro` and `mine-learnings` readers are now aligned with the telemetry writer layout (tele-07).
- **Queue integrity recovery** — the queue integrity envelope is recoverable via audit/heal.
- **Integrity refusal cleanup** — cleaned up integrity refusals, hygiene sidecars, and foreground validations.

### Documentation

- Added ADR-026 documenting slim markdown quality gates (vgr-02).
- Added enforcement-walls adversarial rehearsal documentation (ewl-06).
- Added plan-durability hardening PRD and pdh-01/pdh-02 plans.
- Added usage-cost telemetry plan and ADR-025 on freshness.
- Added validate-gate-review PRD and vgr-01..05 plans.
- Recovered and landed telemetry-fidelity PRD and plans.
- Synced multiple plans to implementation reality after closure.

---

## [1.0.0] — 2026-07-12

**First stable release.** This is a major version bump: the legacy per-skill binaries are retired in favor of the unified `aet` multicall binary, which is a breaking change for any scripts or muscle memory that invoke the old binaries directly.

### Added

- **`aet` unified binary** — a single multicall dispatcher that routes to all toolkit subcommands, with an `aet install` subcommand and on-invocation PATH self-repair. Replaces the collection of separate legacy binaries (cli-01…05).
- **Machine-readable status** — toolkit bins expose `build_parser()` and a `status --json` output for scripted inspection (cli-02).
- **skills-lint invocation checker** — a new lint that validates skill invocation patterns (cli-03).
- **Workflow-as-data pipelines** — pipeline stage sequences are now declared in a packaged workflow file with a schema and loader, and plans route gated stages from YAML frontmatter (wfd-01…03).
- **Workflow lint** — `make validate` now lints workflow definitions, with a team-variant exit-gate proof (wfd-04).
- **Telemetry panel** — a local, stdlib-launched archive viewer with a Plans lens: plan model, tabs, plan list, and plan detail with a pipeline spine, consolidated timeline, and run chips (thp-05/06).
- **Telemetry retention pruning** — a prune CLI with active-run protection, a worktree-based project slug, and an archive slug migration helper (thp-02/03/04).
- **git-refs task backend** — `aet-work` can store task state in git refs as an alternative to the local JSON queue, with backend sealing and a parity suite (frh-13/14).
- **Curated sprint intake** — `aet-work` sync no longer auto-adds plans; intake parks them as ready or blocked for explicit curation (frh-15).
- **R-trace decision templates** — `aet-plan` gains requirement-traceability templates and prose, backed by ADR-020 and ADR-021 (rdm-01/02).

### Changed

- **aet-work orchestrator hardening** — locked, atomic queue writes; a tamper-evident mutation guard with a run lease; and evidence-gated task completion that requires a structured gate verdict (frh-01/02/10/11/17).
- **Live frontier batch exit** — the orchestrator widens the scheduling frontier and exits cleanly when idle instead of spinning (frh-16).
- **Process isolation** — batch children spawn in a new session and are killed by process group on timeout or shutdown (frh-03).
- **aet-retro telemetry** — now emits structured `learning_candidate` records for downstream mining (frh-12).
- **`make validate`** — wires pytest and ruff into the validation gate (frh-04).

### Fixed

- **Orchestrator false-completion** — the orchestrator now requires commits before marking a task complete and reconciles `pending_blockers` against settled history.
- **Verifier stage detection** — the verifier reads the footer stage instead of scanning body mentions.
- **Per-kind verdict paths** — verdicts are published to per-kind paths so stages read the correct evidence.
- **Worktree reuse** — `aet-work` reuses existing worktrees that are up-to-date or dirty instead of recreating them.

### Removed

- **Legacy skill binaries** — the many separate per-skill binaries are retired in favor of the `aet` multicall binary (cli-05).
- **Hardcoded pipeline module** — `pipeline.py` deleted; stage sequencing now lives in the workflow file (wfd-03).
- **Legacy status vocabulary** — retired from the queue library, read side, and state layer (frh-06/07).
- **Dead orchestrator layer** — removed unused dead code (frh-08).

### Documentation

- Added ADR-019, ADR-020, and ADR-021, and indexed the ADR set.
- Added PRDs and plan suites for fable-review hardening (frh-01…18), workflow-as-data extraction (wfd-01…04), the `aet` binary (cli-01…05), and telemetry hygiene & the plan-centric panel (thp-01…06).
- Added the p3 enforcement-walls plan set (ewl-01…06) and PRD; retired the abandoned ewl-02 plan while retaining its trail.

---

## [0.10.0] — 2026-07-09

### Added

- **aet-retro command** — `aet-evolve` now includes an automated run-review command that reads per-task telemetry archives and narrative reports to surface errors, performance issues, and actionable improvements after every `aet-work run`.
- **GitHub Issues task backend** — `aet-work` can now use GitHub Issues as the queue backend instead of local JSON files. Plans pushed to the queue become GitHub issues with labels, and state transitions sync bidirectionally.
- **Impact-scoped QA tests** — `aet-qa` defaults to tests that touch the changed files, with an exact fallback to the full suite when the scoped run does not cover every modified path.
- **Stage-failure triage checklist** — `aet-qa` adds a structured triage checklist for failures during plan, review, QA, or ship stages.
- **Review scope noise filter** — `aet-review` tightens its scope lens and adds a project-level noise filter so reviewers focus on the current change instead of unrelated project patterns.
- **Manual merge closure** — `aet-ship` and `aet-state` can close a task from a CLI-supplied branch or merge commit when a PR is merged outside the orchestrator.
- **Queue self-heal audit** — `aet-state heal` reconciles queued tasks against git ground truth and can repair stale state.
- **Testing strategy template** — `aet-setup` scaffolds a `docs/references/testing-strategy.md` example for new projects.

### Changed

- **aet-work orchestrator reliability** — per-task wall-clock timeout, inner heartbeat, and guaranteed cleanup/summary reporting replace the single outer-shell timeout.
- **Worktree freshness** — `aet-work` refreshes `origin/main` before creating or reusing a worktree, and rebases existing worktrees in place when `origin/main` advances.
- **Hygiene noise reduction** — queue mutations detected during hygiene checks are now informational instead of blocking, and plan-drift warnings are logged without halting the run.
- **aet-setup scaffolding** — `docs/references/` now includes a reference-README example, and the skill/checklist guide projects through the new docs scaffolding.

### Fixed

- **aet-work orchestrator crash** — eliminated `NameError: read_queue` by using the configured backend to load queue state.
- **Stale queue writes** — `aet-work` re-reads queue state after `aet-state` transitions to avoid overwriting concurrent updates.
- **Plan closure commits** — `aet-state record-merge` now auto-commits plan footer updates after merge verification.
- **Merged footer formatting** — plan merged footers use consistent underscore emphasis.
- **aet-retro telemetry source** — `aet-retro` reads per-task telemetry archives instead of the removed single `.agents/execution.log.jsonl`.
- **aet-evolve mine-learnings** — restored missing `sys` import.

### Removed

- **aet-discover skill** removed from the toolkit. Discovery workflows remain possible with `aet-plan` and manual product-definition artifacts.

### Documentation

- Added ADR-013 and the QES plan suite documenting the ephemeral sprint-board model.
- Added GitHub Issues task backend PRD and implementation plans.
- Updated `docs/CONVENTIONS.md` and skill guidance to describe the toolkit as a distributed system rather than individual skills.
- Added upgrade guides index and linked it from `README.md`.
- Documented retro learnings from the telemetry-driven skill hardening run.

---

## [0.9.1] — 2026-07-06

### Fixed

- **README**: installation commands now point to the correct repository (`https://github.com/thebrightnest/ae-toolkit`).
- **README**: `npx skills` examples use the `.agents/skills` standard path and omit `.git` from URLs.
- **README**: corrected AET binary installation instructions.

### Changed

- Removed accidentally committed presentation files from the repository.

---

## [0.9.0] — 2026-06-30

### Added

- **Direct telemetry archive** — the orchestrator writes per-task JSONL logs directly to `~/.aet/telemetry/{project-slug}/{date}/{run-id}/`, so telemetry survives project worktree deletion.
- **Per-task telemetry files** — each task writes to its own JSONL file, eliminating concurrent-write races on a shared project log.
- **Run completion status** — every orchestrator run writes a `last-run.json` summary with outcome, task counts, and wall-clock time.
- **Plan-level pipeline override** — plans can declare `pipeline: minimal|standard|full` in YAML frontmatter to control orchestrator isolation per task.

### Changed

- **aet-evolve**: `mine-learnings` now reads the dated archive layout directly; `ingest-telemetry` is no longer required.
- **aet-work**: `report` summarizes telemetry from the archive instead of `.agents/execution.log.jsonl`.
- **aet-plan**: plan frontmatter now documents the optional `pipeline` field.
- **aet-validate-scope**: validates `pipeline` frontmatter values when present.

### Removed

- **aet-evolve**: Removed `ingest-telemetry`; the orchestrator archives telemetry automatically at write time.
- **aet-work**: No longer creates `.agents/execution.log.jsonl`.

### Documentation

- Updated `docs/telemetry-guide.md` for the direct-archive flow.
- Added ADR-012 documenting the direct telemetry archive and per-task logs.

---

## [0.8.0] — 2026-06-22

### Added

- **Telemetry learning system** — six-part update that enriches the telemetry schema, warms worktree dependencies, reuses stage-group sessions, scopes tests to the diff, archives learnings across projects, and packages the whole flow. See `docs/telemetry-guide.md`.
- **aet-setup**: Centralized AET skill binary installation (`install-aet-binaries`) so skills expose their executables on `PATH` consistently.
- **aet-evolve**: `mine-learnings` now parses narrative markdown reports (QA, review, CSO, verification) in addition to structured JSONL records.

### Changed

- **aet-work**: `init-queue` now reconciles terminal state from `.agents/work-history.jsonl` and git, and reconciles plan footer stages on intake.
- **aet-work**: `sync` only validates candidate plans and tolerates legacy dependency sections in already-queued plans.
- **aet-state**: `record-merge` and `derive` now accept merge verification by `merge_commit` alone, removing the requirement for a local branch.

### Fixed

- **aet-work**: Skip main-hygiene check in batch-spawned children so unattended orchestrator runs don't deadlock on already-pulled `origin/main`.
- **Build**: `aet-work/bin/report` is now executable so the installer exposes it on `PATH`.

### Documentation

- Added `docs/telemetry-guide.md` with the telemetry ingestion, archive, and mining workflow plus cross-references from affected skills.

---

## [0.7.0] — 2026-06-19

### Added

- **aet-work**: Forward-only deterministic work state. State is recorded forward through `aet-state transition`, stored in `state` with `history[]`, and terminal tasks are sealed to `.agents/work-history.jsonl`.
- **aet-work**: Validated frontmatter contract for plans (`id`, `blocked_by`, `size`). Intake now fails closed on malformed or legacy plan files.
- **aet-work**: `aet-state record-merge` resolves real squash-merge SHAs and records merge commits deterministically.
- **aet-work**: `run-one` hardening with plan-presence guard, worktree/branch hygiene gate, and telemetry.
- **aet-design-system-creation**: Commands section for design-system, design-review, and design-check workflows.
- **aet-validate-scope**: Closure checks for planning and validation skills.

### Changed

- **aet-work**: `status`, `next`, and the orchestrator now read stored `state` with zero git calls; the old `derive` path becomes an explicit human-run `audit`.
- **aet-work**: Pipeline stages are now recorded as `in_progress` sub-states instead of plan-footer breadcrumbs.
- **aet-work**: `init-queue` and `sync` now consult `.agents/work-history.jsonl` to skip already-settled plans.
- **aet-release-prep**: Fixed version-bump detection and `v`-prefix handling when tags are the version source.

### Fixed

- **aet-ship**: Stage-aware review/CSO gate.
- **aet-work**: Orchestrator no longer enters a runaway spawn loop.
- **aet-work**: Batch worktree is reused in single-task orchestrator subprocess.
- **aet-work**: Task IDs are derived without the hard-coded `-plan.md` suffix.
- **Build**: Skill packaging is now deterministic.

### Documentation

- Added deprecation and backward-compatibility inventory (`docs/audits/deprecation-inventory.md`).
- Added upgrade guide for existing AET projects (`aet-work/references/upgrading-existing-project.md`).
- Added ADR-011 documenting forward-only deterministic work state and settled-history semantics.

---

## [0.6.0] — 2026-06-16

### Added

- **aet-work**: Active-only status view. `status` now reports only active tasks and highlights discrepancies between stored and derived statuses.
- **aet-work**: `cleanup` now archives terminal tasks atomically before removing their worktrees.
- **Unified orchestrator**: Finalized orchestrator cleanup and routed `aet-plan` implementation flows through `aet-work`.

### Changed

- **aet-work**: `status` view now includes `done` tasks in active reporting and removes the archived-tasks note.
- **docs/CONVENTIONS.md**: Added Package-Deliverable Rules section requiring all runtime skill rules to live inside skill packages.

### Fixed

- **aet-ship** and **aet-work**: Worktrees now branch from `origin/main`, independent branches are rebased onto `origin/main` before shipping, stacked branches open against their parent, and PR scope audits flag global files.
- **Orchestrator**: Fixed CLI adapter to use real `kimi`/`claude` flags, preserved queue dict-wrapper format on write, and copied untracked plan/PRD files into worktrees.
- **aet-state**: `derive` now verifies `merge_commit` ancestry before marking tasks as merged.
- **aet-work**: Removed project-specific `app/node_modules` symlink from worktree setup.

### Documentation

- Added `docs/retros/2026-06-16-aet-work-pr-scope-retro.md` documenting the worktree/ship hygiene incident.
- Updated `.agents/reference/skill-writing-guide.md` with package-deliverable checklist items.

---

## [0.5.1] — 2026-06-11

### Added

- **AGENTS.md**: Analysis-to-action discipline guardrail. When analysis identifies a principle violation, the agent must state the conclusion and propose the fix — not offer options that preserve the violation.

### Changed

- **aet-work**: `aet-state` helper is now centralized in `aet-work/bin/aet-state` alongside the orchestrator. `aet-setup` no longer scaffolds a per-project copy.
- **aet-setup**: Scaffold template now includes the analysis-to-action discipline guardrail.

---

## [0.5.0] — 2026-06-11

### Added

- **aet-verify**: New skill for conditional live verification. Three modes — foundation smoke checks, feature evidence capture, and bug reproduction with step-by-step evidence capture.
- **aet-upgrade**: New skill for dependency and framework upgrade planning. Analyzes changelogs, greps codebase for affected patterns, classifies risk per breaking change, and produces a risk-mapped upgrade plan.
- **aet-work**: Unified orchestrator with session-isolated pipeline. Replaces the standalone `aet-pipeline-implement` skill with a centralized Python orchestrator that spawns fresh agent sessions per pipeline stage, eliminating context leakage between skills.
- **aet-work**: Ground-truth status derivation via centralized `aet-state` helper. Queue commands now compute derived statuses from git ground truth and surface discrepancies between stored and actual states.
- **aet-prime**: Repurposed as triage front door. Added work-class routing and active PRD/plan stage tracking to classify incoming requests before context loading.
- **aet-evolve**: Added trigger schema for learnings (keyword-based matching), retro debt check (verify past retro action items), and escalation ladder for unresolved systemic issues.
- **aet-validate-scope**: Integrated UI Coverage Lens from `aet-validate-ui`. Seven-category UI/UX validation with blocking/warning severity ratings.
- **Build system**: New `scripts/build-skills.py` with incremental packaging, dependency graph validation, and comprehensive build system test suite.
- **Validation**: Enhanced `scripts/validate-skills.sh` with composition contradiction detection and improved guardrails.
- **Testing**: Added unit tests for orchestrator lib modules (`tests/test_*.py`).

### Changed

- **aet-work**: `run` command now invokes the centralized Python orchestrator instead of generating bash scripts. Improved worktree isolation and parallel execution semantics.
- **aet-pipeline-plan**: Streamlined pipeline sequence. Removed `aet-pipeline-implement` references; all implementation flows now route through `aet-work`.
- **aet-setup**: Enhanced with additional guardrails and setup validation procedures.
- **aet-ship**: Updated branch lifecycle and release gating procedures.
- **aet-bug-report**: Updated investigation procedures and reference materials.
- **aet-plan**: Enhanced validation strategy gate with explicit test coverage requirements per source file.
- **aet-tdd**: Added coverage completeness hard gate before `tdd-complete`.
- **aet-implement**: Updated execution routing to use `aet-work`.
- **docs/CONVENTIONS.md**: Synced with v1.2 toolkit conventions and clarified planning artifact directory rules.

### Removed

- **aet-pipeline-implement**: Skill removed. Functionality unified into `aet-work` orchestrator.
- **aet-validate-ui**: Standalone skill removed. UI validation folded into `aet-validate-scope`.

### Fixed

- **aet-verify**: Resolved validation errors for preamble formatting and trigger collision.
- **aet-work**: Orchestrator now verifies commits exist before marking tasks as done.

---

## [0.4.0] — 2026-06-08

### Added

- **aet-review**: Rewrote the **Tests** lens into a concrete two-part coverage completeness check. New source files without test coverage are classified as `fix-now`; diffs introducing both backend routes and frontend API clients without an API boundary test are also `fix-now`. Added `references/test-coverage-check.md` with the mechanical procedure. ([PR #33](https://github.com/thebrightnest/ae-toolkit/pull/33))
- **aet-tdd**: Added **Coverage Completeness** hard gate before `tdd-complete`. The `plan-tests` step now enumerates every new source file introduced by the plan and mandates at least one named test per file. Added **API boundary integration test** mandate for vertical slices touching both frontend and backend. Added `references/api-boundary-tests.md` and `docs/adr/008-test-coverage-completeness.md`. ([PR #34](https://github.com/thebrightnest/ae-toolkit/pull/34))
- **aet-plan**: Added **Validation strategy gate** to the `plan` command procedure. Plans must now name at least one specifically named test for each new source file or module, and distinguish between unit, integration, and API boundary tests. Frames under the Cross-Cutting Completeness framework (ADR-001). Updated `.agents/templates/plan-template.md` with structured checklist items replacing the generic "Manual verification step". ([PR #35](https://github.com/thebrightnest/ae-toolkit/pull/35))
- **aet-qa**: Added **coverage gate** to the QA procedure. After the automated test suite runs, the agent now checks coverage thresholds and flags any new source files with 0% coverage. Added coverage tooling note with language-appropriate defaults (Laravel, React, etc.). ([PR #36](https://github.com/thebrightnest/ae-toolkit/pull/36))

### Fixed

- **aet-work**: `cleanup` command now correctly handles the legacy `merge_verified` status by normalizing it to `merged` before removal.

## [0.3.0] — 2026-06-02

### Added

- **aet-release-prep**: New skill for automated release preparation. Analyzes commits since the last tag, detects versioning scheme, suggests semantic version bumps, and updates `CHANGELOG.md`.
- **aet-pipeline-implement**: Terminal resilience improvements. Added step-budget mode for long-running pipelines, temporary report files for progress tracking, and `gitignore` safety checks to prevent leaking generated artifacts.
- **aet-work**: Queue state hardening. Added `merged` and `abandoned` terminal statuses; `done` is deprecated but retained for backwards compatibility. New `mark-terminal` command enforces `merge_verified: true` before marking `merged`, and requires a `reason` for `abandoned`. `status` now validates `worktree` fields and flags stale entries. `cleanup` repairs stale worktree fields (missing directories or 0 commits ahead of main). Orchestrator template updated to record `worktree`/`branch` metadata and `completed_at` timestamps. ([PRD](docs/prds/workflow-audit-fixes-prd.md))
- **aet-work**: Orchestrator auto-removes empty worktrees. After a task exits (success or failure), the orchestrator checks if the worktree has 0 commits ahead of main. If so, it removes the worktree and clears the queue's `worktree` field, preventing disk-space leaks from failed or no-op tasks.
- **aet-work**: Orchestrator copies untracked plan and PRD files into worktrees read-only. This ensures agents can reference new plans that exist in the main working directory but have not yet been committed.
- **aet-plan**, **aet-pipeline-implement**: Added explicit guardrails against creating `docs/plans/plans/` or any nested duplicate directory. Agents are instructed to write plan files directly to `docs/plans/{filename}` only.
- **Repo hooks**: Pre-push deletion short-circuit. Added a safety hook that prevents accidental deletion of protected branches during push operations.

### Changed

- **aet-ship**: Branch lifecycle & release gating. Improved branch tracking through the shipping pipeline with clearer release readiness checks and gating logic.
- **docs/adr/003-toolkit-level-branch-safety.md**: Accepted. Validated by Coverage Batch 2 cleanup findings.

### Fixed

- **aet-work**: Fixed orchestrator timeout on long-running `aet-pipeline-implement` tasks. The skill now explicitly specifies `timeout=7200` (2 hours) when spawning the orchestrator, and instructs agents to use `--afk` (or equivalent headless mode) instead of `--yolo` so approval gates auto-dismiss in unattended background jobs. Updated reference orchestrator template and generated script accordingly.

## 0.2.0

### Changed

- **aet-work**, **aet-plan**, **aet-pipeline-plan**: Enforced plan atomicity boundary. `docs/plans/` is now explicitly for atomic, implementable task plans only. Roadmaps, audits, and meta-plans must be stored in `docs/roadmaps/` or `docs/audits/`. `aet-work sync` now validates atomicity and skips non-atomic documents. `AGENTS.md` workflow guardrails updated to reflect the new directory convention. ([PRD](docs/prds/work-queue-atomicity-boundary-prd.md))

- **docs/CONVENTIONS.md**: Added "Planning Artifact Directories" section documenting the directory convention for atomic plans, roadmaps, audits, and PRDs. Created ADR-006 recording the structural boundary decision and its consequences. ([ADR](docs/adr/006-work-queue-atomicity-boundary.md))

- **aet-pipeline-plan**: Removed `aet-discover` from the pipeline sequence. The pipeline now runs `aet-plan → aet-validate-ui (optional) → aet-validate-scope` for validated ideas and known tasks. `aet-discover` remains a standalone skill for raw, unvalidated ideas. ([PRD](docs/prds/pipeline-plan-remove-discover-prd.md))

- **aet-pipeline-plan**: Integrated `aet-validate-ui` as an optional step in the planning pipeline. Added skip logic for no-UI features, a hard gate for blocking UI/UX findings, and `ui-validated` as a resumable stage.

- **aet-work**: Unified `run` command with OS-process isolation. Removed the broken cooperative `run` loop and the `run-scripted` command. The new `run` generates a bash orchestrator that spawns fresh OS processes per task — the proven mechanism formerly known as `run-scripted`. Updated `references/context-isolation.md` to explain why cooperative clearing failed. Added ADR-004 documenting the decision.

### Added

- **Execution Mode Interaction Model**: Introduced `AET_EXECUTION_MODE=unattended` as the formal signal for unattended orchestration, replacing the ad-hoc `AET_ORCHESTRATOR=1` env var. Added ADR-005, updated `docs/CONVENTIONS.md` and `.agents/reference/skill-writing-guide.md` with the contract and bypass protocol. Updated `aet-implement`, `aet-pipeline-implement`, `aet-work`, and `aet-setup` skills to detect and respect the new variable. Added a validator rule in `scripts/validate-skills.sh` to flag skills with interactive approval gates that don't mention `AET_EXECUTION_MODE`. ([PRD](docs/prds/execution-mode-interaction-model-prd.md))

- **Task Size Guardrails**: Introduced a dual-limit model (human-time + AI-complexity) across all planning skills. `aet-plan` now auto-splits oversized stories and tasks, `aet-work` validates sizes on queue sync, and `aet-implement` refuses to start `⚠️ ATOMIC OVERSIZED` tasks without explicit override. Documented in `docs/CONVENTIONS.md`. ([PRD](docs/prds/task-size-guardrails-prd.md))

- **aet-implement**: Added visual/CSS verification to the validation strategy. If a plan includes renderer/UI work, the implementation phase now requires verifying that all custom `className` values have corresponding CSS definitions.
- **aet-review**: Added `references/css-completeness-check.md` — a mechanical procedure for verifying CSS completeness during code review.
- **Cross-Cutting Completeness Framework**: Introduced ADR-001 documenting the framework for catching implicit obligations across domains (CSS, i18n, assets, icons, feature flags). CSS completeness is the first proven example.
- **plan-template**: Added a "Renderer / UI Tasks" subsection to the plan template, reminding authors to verify CSS styles for all custom `className` values.

- **aet-work parallel execution**: `aet-work run` now executes independent tasks in parallel using bash job control. Default concurrency cap is 4 jobs (override via `AET_WORK_JOBS`), with a hard ceiling of 8. Features drain-on-failure (running tasks finish, new spawns halt), orphaned in-progress detection on resume, and end-of-run summary. Added 16 integration tests in `scripts/test-orchestrator.sh`. ([PRD](docs/prds/aet-work-parallel-execution-prd.md))

### Fixed

- **aet-work**: Runtime detection in `run` now uses agent self-identification instead of a hard-coded PATH/env-var priority list. The agent executing `aet-work run` reports its own CLI command and flags, eliminating mis-detection when multiple agents are installed. ([PRD](docs/prds/aet-work-runtime-self-detection-prd.md))

- **aet-ship**: Added stacked branch detection to the `ship` procedure. When a branch was not branched directly from `main`, `aet-ship` now injects a `⚠️ STACKED PR` warning into the PR body and prints a terminal stop-note. Prevents the class of incident where a stacked PR is merged against a stale base after its parent lands in main.
