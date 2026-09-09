"""Abstract backend interface for aet-work task storage."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

# Posture identifiers. A project is "shadow" when no project-scope config exists;
# it is "shared" when an in-tree .agents/aet-config.json is present. Shadow is
# the safe default: refs/aet/* are never pushed and no AET artifact reaches the
# working tree.
SHADOW_POSTURE = "shadow"
SHARED_POSTURE = "shared"


class TaskBackend(ABC):
    """Pluggable backend interface for loading, saving, and mutating the work queue.

    The only storage implementation is :class:`GitRefsBackend`, which keeps
    state in ``refs/aet/*`` inside the repository. Callers should use the
    public methods here rather than importing queue helpers directly.
    """

    @abstractmethod
    def load(self, verify: bool = True) -> dict[str, Any]:
        """Return the current queue and settled history.

        Returns a dict with at least ``queue`` (list of task dicts) and
        ``history`` (list of settled task dicts).

        ``verify`` is retained for interface compatibility but is ignored by
        the git-refs backend: its envelope carries a ``schema_version`` and the
        live refs are treated as ground truth (ADR-055).
        """

    @abstractmethod
    def save(
        self, queue: list[dict[str, Any]], wrapper: dict[str, Any] | None = None
    ) -> None:
        """Persist ``queue`` to the backend store.

        ``wrapper`` contains optional envelope metadata (e.g. ``source_prd``,
        ``queue_updated_at``) that the git-refs backend merges into the
        ``refs/aet/meta/queue`` envelope.
        """

    @abstractmethod
    def close(self) -> None:
        """Release any resources held by the backend."""

    @abstractmethod
    def sync_task(self, task: dict[str, Any], is_new: bool) -> None:
        """Notify the backend that a task was synced.

        ``is_new`` is ``True`` when the task was just appended to the queue
        and ``False`` when it already existed. The git-refs backend has no
        external mirror and leaves this as a no-op.
        """

    def on_transition(
        self,
        task_id: str,
        from_state: str | None,
        to_state: str,
        evidence: dict[str, Any] | None = None,
    ) -> None:
        """Optional hook called after a transition has been persisted.

        Backends such as GitHub Issues can override this to update labels or
        other external state. The default implementation does nothing.
        """
        return

    def close_task(
        self, task_id: str, evidence: dict[str, Any] | None = None
    ) -> None:
        """Optional hook called after a terminal task is sealed.

        Backends such as GitHub Issues can override this to close the
        corresponding external issue. The default implementation does nothing.
        """
        return

    def fetch(self) -> None:
        """Pull remote state into the backend store.

        The git-refs backend fetches the ``refs/aet/*`` namespace from
        ``origin``. The default implementation does nothing.
        """
        return

    def push(self, *, mandatory: bool = False) -> bool:
        """Push backend state to the forge remote.

        ``mandatory`` is ``True`` for terminal closure boundaries where the push
        is part of the durability guarantee.

        Returns ``True`` when the push succeeded or when there is nothing to push
        (no remote), and ``False`` on a best-effort failure. When ``mandatory``
        is ``True``, failures are raised as :exc:`RefsPushError` with a named
        remedy instead of returning ``False``.
        """
        return True

    def seal(self, task_id: str, history_file: str) -> dict[str, Any]:
        """Move a terminal task from the live queue to the settled history log.

        The git-refs backend overrides this to drop the per-task ref and write
        a tombstone under ``refs/aet/sealed/<id>`` before appending the record
        to the shared history JSONL.

        The caller (``aet-state``) already holds the queue lock, so this method
        does not re-acquire it: the queue module is loaded twice in-process
        (as ``aet_queue`` by ``aet-state`` and as ``queue`` by the backends),
        and a second independent ``flock`` file descriptor to the same lock file
        would self-deadlock under POSIX ``flock`` semantics.
        """
        raise NotImplementedError("seal must be implemented by the storage backend")

    def read_epic(self) -> dict[str, Any] | None:
        """Return the active epic declaration from the backend, or None."""
        return None

    def set_epic(
        self,
        branch: str,
        title: str | None = None,
        body_file: str | None = None,
    ) -> dict[str, Any]:
        """Set the active epic declaration in the backend."""
        raise NotImplementedError

    def clear_epic(self) -> None:
        """Clear the active epic declaration from the backend."""
        raise NotImplementedError
