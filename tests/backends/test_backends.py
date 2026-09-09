"""Tests for aet-work backend abstraction."""

import subprocess
import tempfile
import unittest
from abc import ABC
from pathlib import Path

from aet.backends.base import TaskBackend
from aet.backends.factory import (
    LegacyTaskBackendError,
    QueueOutsideRepositoryError,
    create_backend,
)
from aet.backends.git_refs_backend import GitRefsBackend


class TestTaskBackend(unittest.TestCase):
    def test_task_backend_is_abstract(self):
        with self.assertRaises(TypeError):
            TaskBackend()

    def test_task_backend_is_abc_subclass(self):
        self.assertTrue(issubclass(TaskBackend, ABC))


class TestFactory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.queue_file = str(Path(self.tmp.name) / "aet-queue")
        self.history_file = str(Path(self.tmp.name) / "work-history.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def test_factory_returns_git_refs_backend_by_default(self):
        subprocess.run(["git", "init", "-q", self.tmp.name], check=True)

        backend = create_backend(
            config_path=str(Path(self.tmp.name) / "missing.json"),
            queue_file=self.queue_file,
            history_file=self.history_file,
        )
        self.assertIsInstance(backend, GitRefsBackend)

    def test_factory_returns_git_refs_backend_with_other_config(self):
        config_path = Path(self.tmp.name) / "aet-config.json"
        config_path.write_text('{"integration_mode": "single-pr"}', encoding="utf-8")
        subprocess.run(["git", "init", "-q", self.tmp.name], check=True)

        backend = create_backend(
            config_path=str(config_path),
            queue_file=self.queue_file,
            history_file=self.history_file,
        )
        self.assertIsInstance(backend, GitRefsBackend)

    def test_factory_raises_migration_error_for_json_backend(self):
        config_path = Path(self.tmp.name) / "aet-config.json"
        config_path.write_text('{"task_backend": "json"}', encoding="utf-8")

        with self.assertRaises(LegacyTaskBackendError) as ctx:
            create_backend(
                config_path=str(config_path),
                queue_file=self.queue_file,
                history_file=self.history_file,
            )
        self.assertIn("migration", str(ctx.exception).lower())

    def test_factory_raises_migration_error_for_any_task_backend_key(self):
        config_path = Path(self.tmp.name) / "aet-config.json"
        config_path.write_text('{"task_backend": "git-refs"}', encoding="utf-8")

        with self.assertRaises(LegacyTaskBackendError):
            create_backend(
                config_path=str(config_path),
                queue_file=self.queue_file,
                history_file=self.history_file,
            )
    def test_factory_raises_queue_outside_repo_error(self):
        with self.assertRaises(QueueOutsideRepositoryError):
            create_backend(
                config_path=str(Path(self.tmp.name) / "missing.json"),
                queue_file=self.queue_file,
                history_file=self.history_file,
            )

    def test_envelope_without_epic_key_loads(self):
        """R-15: an envelope written without the epic key loads and reports no active epic."""
        from aet.backends.git_refs_backend import ENVELOPE_SCHEMA_VERSION

        self.assertEqual(ENVELOPE_SCHEMA_VERSION, 1)
        subprocess.run(["git", "init", "-q", self.tmp.name], check=True)
        backend = create_backend(
            config_path=str(Path(self.tmp.name) / "missing.json"),
            queue_file=self.queue_file,
            history_file=self.history_file,
        )
        # Empty envelope / no envelope ref exists yet
        self.assertIsNone(backend.read_epic())

        # Save an envelope without epic
        backend.save([], wrapper={"source_prd": "docs/prds/test.md"})
        self.assertIsNone(backend.read_epic())
        backend.close()

    def test_set_and_read_epic_declaration(self):
        """R-1: set_epic stores epic declaration and read_epic retrieves it."""
        subprocess.run(["git", "init", "-q", self.tmp.name], check=True)
        backend = create_backend(
            config_path=str(Path(self.tmp.name) / "missing.json"),
            queue_file=self.queue_file,
            history_file=self.history_file,
        )
        epic = backend.set_epic(branch="feat/test-epic", title="Test Epic Title")
        self.assertEqual(epic["branch"], "feat/test-epic")
        self.assertEqual(epic["title"], "Test Epic Title")
        self.assertIn("set_at", epic)

        read = backend.read_epic()
        self.assertIsNotNone(read)
        self.assertEqual(read["branch"], "feat/test-epic")
        self.assertEqual(read["title"], "Test Epic Title")
        self.assertEqual(read["set_at"], epic["set_at"])
        backend.close()

    def test_set_epic_with_body_file(self):
        """R-1: set_epic validates that body_file exists on disk."""
        subprocess.run(["git", "init", "-q", self.tmp.name], check=True)
        body = Path(self.tmp.name) / "epic_body.md"
        body.write_text("Epic description", encoding="utf-8")

        backend = create_backend(
            config_path=str(Path(self.tmp.name) / "missing.json"),
            queue_file=self.queue_file,
            history_file=self.history_file,
        )
        backend.set_epic(branch="feat/test-epic", body_file=str(body))
        read = backend.read_epic()
        self.assertIsNotNone(read)
        self.assertEqual(read["body_file"], str(body))

        with self.assertRaises(ValueError):
            backend.set_epic(branch="feat/test-epic", body_file=str(Path(self.tmp.name) / "nonexistent.md"))

        with self.assertRaises(ValueError):
            backend.set_epic(branch="")

        backend.close()

    def test_clear_epic_declaration(self):
        """clear_epic clears the epic declaration from the envelope."""
        subprocess.run(["git", "init", "-q", self.tmp.name], check=True)
        backend = create_backend(
            config_path=str(Path(self.tmp.name) / "missing.json"),
            queue_file=self.queue_file,
            history_file=self.history_file,
        )
        backend.set_epic(branch="feat/test-epic")
        self.assertIsNotNone(backend.read_epic())

        backend.clear_epic()
        self.assertIsNone(backend.read_epic())
        backend.close()


if __name__ == "__main__":
    unittest.main()
