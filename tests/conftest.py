"""Pytest configuration and offline safety guard (Stage 0B — DEF-024 / DEF-030).

Ensures that normal offline unit tests (tests NOT marked with @pytest.mark.live)
CANNOT accidentally spawn a live `agy` CLI subprocess or consume live model quota.
"""

from __future__ import annotations

import subprocess
from typing import Any
import pytest


class LiveModelInvocationBlockedError(RuntimeError):
    """Raised when an offline unit test accidentally attempts to invoke live `agy` CLI."""


def _is_agy_command(args: Any) -> bool:
    if isinstance(args, (list, tuple)) and args:
        first = str(args[0]).strip().lower()
        return first == "agy" or first.endswith(("\\agy", "/agy", "\\agy.exe", "/agy.exe"))
    if isinstance(args, str):
        stripped = args.strip().lower()
        return stripped.startswith("agy ") or stripped == "agy" or stripped.startswith("agy.exe")
    return False


@pytest.fixture(autouse=True)
def _block_accidental_live_agy_in_offline_tests(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent non-@pytest.mark.live unit tests from accidentally spawning live `agy`."""
    if request.node.get_closest_marker("live") is not None:
        return

    real_popen = subprocess.Popen
    real_run = subprocess.run

    def _guarded_popen(args: Any, *pargs: Any, **kwargs: Any) -> Any:
        if _is_agy_command(args):
            raise LiveModelInvocationBlockedError(
                f"Offline unit test '{request.node.nodeid}' attempted to spawn live 'agy' subprocess without "
                "@pytest.mark.live or subprocess.Popen mock."
            )
        return real_popen(args, *pargs, **kwargs)

    def _guarded_run(args: Any, *pargs: Any, **kwargs: Any) -> Any:
        if _is_agy_command(args):
            raise LiveModelInvocationBlockedError(
                f"Offline unit test '{request.node.nodeid}' attempted to run live 'agy' subprocess without "
                "@pytest.mark.live or subprocess.run mock."
            )
        return real_run(args, *pargs, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", _guarded_popen)
    monkeypatch.setattr(subprocess, "run", _guarded_run)
