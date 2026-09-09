"""Circuit breaker decision logic for the night-shift runtime.

Per-task breaker: the same signature 3x on a single task => quarantine.
Systemic breaker: the same signature across 3 distinct tasks => stop shift.

All breaker state rides the existing git-refs ledger: per-task counts live on
the task record, and the shift-level systemic tally is stored under
``refs/aet/breaker``. No second storage backend is introduced (ADR-030).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

PER_TASK_BREAKER_THRESHOLD = 3
SYSTEMIC_BREAKER_THRESHOLD = 3

BREAKER_REF = "refs/aet/breaker"


def record_failure_signature(
    record: dict[str, Any],
    signature: str,
    timestamp: str | None = None,
) -> None:
    """Append a failure signature to *record*'s ``failure_signatures`` list."""
    record.setdefault("failure_signatures", []).append(
        {"signature": signature} if timestamp is None else {"signature": signature, "ts": timestamp}
    )


def append_failure_if_countable(
    record: dict[str, Any],
    failure_class: Any,
    signature: str,
    timestamp: str | None = None,
) -> bool:
    """Append *signature* to *record*, marking whether it counts for the breaker.

    Returns ``True`` when the signature counts as breaker evidence and ``False``
    when it does not. ``canceled`` failures are not breaker evidence (ADR-030),
    and neither are ``throttled`` ones: the breaker exists to stop a task that
    keeps failing for its own reasons, and three attempts against a closed
    provider window say nothing about the task.

    A ``throttled`` failure is still recorded, carrying ``countable: False``.
    Not recording it hid the class from the only remedy that acts on it —
    ``_finalize_task`` reads the class off this list to stop the run (ADR-065
    decision 3) — so the two decisions cancelled and a closed window requeued
    without limit
    (``docs/bugs/20260828-throttle-remedy-cannot-see-its-own-class.md``).
    ``should_quarantine_task`` and the systemic tally skip non-countable
    entries, which is what keeps decision 2 intact.

    A ``canceled`` failure is still not recorded at all: an operator stopping a
    shift is not evidence of anything, and no remedy reads it back.
    """
    # Import here to avoid a hard dependency on failure.py for pure tests.
    try:
        from aet.failure import FailureClass
    except ImportError:  # pragma: no cover - defensive fallback
        FailureClass = None

    if FailureClass is not None:
        class_value = getattr(failure_class, "value", failure_class)
        if class_value == FailureClass.CANCELED.value:
            return False
        if class_value == FailureClass.THROTTLED.value:
            record_failure_signature(record, signature, timestamp=timestamp)
            record["failure_signatures"][-1]["countable"] = False
            return False
    record_failure_signature(record, signature, timestamp=timestamp)
    return True


def should_quarantine_task(
    record: dict[str, Any],
    threshold: int = PER_TASK_BREAKER_THRESHOLD,
) -> bool:
    """Return True when any countable signature on *record* has reached *threshold*.

    Entries marked ``countable: False`` are evidence for triage, not for the
    breaker: they record a failure that was not the task's fault.
    """
    counts: dict[str, int] = {}
    for entry in record.get("failure_signatures", []):
        if entry.get("countable") is False:
            continue
        sig = entry.get("signature")
        if sig:
            counts[sig] = counts.get(sig, 0) + 1
            if counts[sig] >= threshold:
                return True
    return False


def update_systemic_tally(
    tally: dict[str, set[str]],
    task_id: str,
    signature: str,
) -> dict[str, set[str]]:
    """Return a new tally with *task_id* counted for *signature*.

    Each signature maps to the set of distinct task_ids that have produced it.
    """
    new_tally = {sig: set(task_ids) for sig, task_ids in tally.items()}
    new_tally.setdefault(signature, set()).add(task_id)
    return new_tally


def systemic_tripped(
    tally: dict[str, set[str]],
    threshold: int = SYSTEMIC_BREAKER_THRESHOLD,
) -> str | None:
    """Return the first signature whose distinct-task count reaches *threshold*.

    Returns ``None`` when no signature has crossed the threshold.
    """
    for sig, task_ids in tally.items():
        if len(task_ids) >= threshold:
            return sig
    return None


def systemic_report(tally: dict[str, set[str]]) -> str | None:
    """Return a human-readable systemic breaker report, or None if not tripped."""
    sig = systemic_tripped(tally)
    if sig is None:
        return None
    count = len(tally[sig])
    return f"systemic breaker: signature {sig} x {count} tasks"


class BreakerStore:
    """Persist the systemic breaker tally to ``refs/aet/breaker`` via git."""

    def __init__(self, repo_root: str | Path) -> None:
        self.repo_root = Path(repo_root)

    @staticmethod
    def _stdout_text(result: subprocess.CompletedProcess) -> str:
        """Return *result.stdout* as text, tolerating str or bytes."""
        stdout = result.stdout
        if isinstance(stdout, bytes):
            return stdout.decode("utf-8")
        return stdout or ""

    def _git(self, *args: str, input: bytes | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", str(self.repo_root), *args],
            input=input,
            capture_output=True,
        )

    def _write_blob(self, data: bytes) -> str:
        result = self._git("hash-object", "-w", "--stdin", input=data)
        result.check_returncode()
        return self._stdout_text(result).strip()

    def _ref_sha(self, ref: str) -> str | None:
        result = self._git("rev-parse", "--verify", "-q", ref)
        if result.returncode != 0:
            return None
        return self._stdout_text(result).strip()

    def _read_blob(self, sha: str) -> bytes | str:
        result = self._git("cat-file", "-p", sha)
        result.check_returncode()
        return result.stdout

    def load(self) -> dict[str, set[str]]:
        """Load the systemic tally from git, returning an empty dict if absent."""
        sha = self._ref_sha(BREAKER_REF)
        if sha is None:
            return {}
        try:
            data = json.loads(self._read_blob(sha))
        except (json.JSONDecodeError, subprocess.CalledProcessError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {
            sig: set(task_ids)
            for sig, task_ids in data.items()
            if isinstance(task_ids, list)
        }

    def save(self, tally: dict[str, set[str]]) -> None:
        """Persist *tally* to ``refs/aet/breaker`` as canonical JSON."""
        payload = {
            sig: sorted(task_ids) for sig, task_ids in sorted(tally.items())
        }
        data = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        sha = self._write_blob(data)
        self._git("update-ref", BREAKER_REF, sha).check_returncode()

    def clear(self) -> bool:
        """Delete ``refs/aet/breaker`` if present.

        Returns ``True`` if the ref existed and was deleted, ``False`` if absent.
        """
        if self._ref_sha(BREAKER_REF) is None:
            return False
        result = self._git("update-ref", "-d", BREAKER_REF)
        result.check_returncode()
        return True

    def reset(self) -> bool:
        """Alias for :meth:`clear`."""
        return self.clear()
