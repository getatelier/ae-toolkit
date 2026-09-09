"""Smoke tests that every CLI module exposes a loadable Typer app.

The legacy requirement that every binary expose ``build_parser()`` has been
retired with the argparse dispatch layer.  These tests verify that each module
still loads and that its Typer ``app`` exposes the expected commands, options,
and callbacks.
"""

from __future__ import annotations

import importlib
import unittest
from pathlib import Path

import typer
from typer.testing import CliRunner

_REPO_ROOT = Path(__file__).parents[2]

# Module paths relative to the repo root and the command/callback shape we
# expect after the Typer consolidation.
_MODULES = {
    "aet.cli.aet_state": {
        "commands": [
            "audit",
            "heal",
            "validate",
            "reset",
            "transition",
            "set-stage",
            "record-merge",
            "backfill-specs",
            "reconcile",
        ]
    },
    "aet.cli.backlog": {"commands": ["add"]},
    "aet.cli.configure_backend": {"callback": True},
    "aet.cli.desk": {"commands": ["merge", "abandon"], "callback": True},
    "aet.cli.docs": {"commands": ["lint", "generate"]},
    "aet.cli.gate": {"commands": ["submit", "review"]},
    "aet.cli.harness_guard": {"commands": ["install", "check"]},
    "aet.cli.hooks": {"commands": ["install", "check"]},
    "aet.cli.metrics": {"callback": True},
    "aet.cli.mine_learnings": {"callback": True},
    "aet.cli.next": {"callback": True},
    "aet.cli.orchestrator": {"callback": True},
    "aet.cli.panel": {"callback": True},
    "aet.cli.plan": {"commands": ["validate"]},
    "aet.cli.plans": {"commands": ["lint"]},
    "aet.cli.reconcile": {"callback": True},
    "aet.cli.release_prep": {"callback": True},
    "aet.cli.report": {"callback": True},
    "aet.cli.retro": {"callback": True},
    "aet.cli.ship": {
        "commands": ["default", "gate", "open", "open-epic", "merge", "split", "verify", "close", "record-merge"]
    },
    "aet.cli.sprint": {"commands": ["add", "intake"]},
    "aet.cli.status": {"callback": True},
    "aet.cli.sync": {"commands": ["sync"]},
    "aet.cli.validate_workflows": {"callback": True},
}


def _load_module(module_name: str):
    # Always import through the normal module cache; do *not* pop/reload the
    # module, because Typer parameter metadata is keyed by function identity
    # and reimporting breaks apps held by other test modules.
    return importlib.import_module(module_name)


class TestModuleLoadsAndExposesTyperApp(unittest.TestCase):
    def _command_names(self, app: typer.Typer) -> set[str]:
        return {c.name for c in app.registered_commands if c.name is not None}

    def _has_callback(self, app: typer.Typer) -> bool:
        return app.registered_callback is not None

    def test_review_module_no_longer_exists(self):
        """The old review.py binary was folded into ``aet.cli.gate``."""
        self.assertFalse((_REPO_ROOT / "src" / "aet" / "cli" / "review.py").exists())

    def test_all_modules_expose_a_typer_app(self):
        for module_name in _MODULES:
            with self.subTest(module=module_name):
                module = _load_module(module_name)
                self.assertTrue(hasattr(module, "app"), f"{module_name} has no app")
                self.assertIsInstance(module.app, typer.Typer)

    def test_expected_commands_registered(self):
        for module_name, spec in _MODULES.items():
            commands = spec.get("commands")
            if commands is None:
                continue
            with self.subTest(module=module_name):
                module = _load_module(module_name)
                self.assertEqual(
                    self._command_names(module.app),
                    set(commands),
                )

    def test_expected_callbacks_registered(self):
        for module_name, spec in _MODULES.items():
            if not spec.get("callback"):
                continue
            with self.subTest(module=module_name):
                module = _load_module(module_name)
                self.assertTrue(
                    self._has_callback(module.app),
                    f"{module_name} is missing a registered callback",
                )

    def test_help_loads_for_every_module(self):
        runner = CliRunner()
        for module_name in _MODULES:
            with self.subTest(module=module_name):
                module = _load_module(module_name)
                result = runner.invoke(module.app, ["--help"])
                self.assertEqual(
                    result.exit_code,
                    0,
                    f"{module_name} --help failed:\n{result.output}",
                )


if __name__ == "__main__":
    unittest.main()
