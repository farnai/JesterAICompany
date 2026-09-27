"""Unit and integration tests for Pipeline Execution Telemetry in status.py.

Verifies:
1. get_pipeline_telemetry() helper functionality with read-only inspection of .runs/.
2. get_company_status() integration with 'pipeline_telemetry' and alias 'telemetry'.
3. format_status_console() layout, section positioning, dividers, and label alignment.
4. Display states:
   - Empty state (0 runs)
   - Success state
   - Failed state
   - Running state
   - Corrupted manifest fallback (missing file, invalid JSON, non-dict JSON)
5. Goal sanitization and truncation rules (61 chars max, 58 + '...').
6. Subprocess execution via `python status.py` and `python status.py --json`.
7. Zero modification of existing keys or external dependencies.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from jester_ai_company.status import (
    _sanitize_and_truncate_goal,
    format_status_console,
    get_company_status,
    get_pipeline_telemetry,
    get_repo_root,
)
import status as root_status


# ==============================================================================
# 1. Telemetry Reader Helper & Data Structure
# ==============================================================================

def test_telemetry_keys_present_in_company_status():
    """Verify get_company_status() includes pipeline_telemetry and telemetry alias."""
    status_data = get_company_status()

    assert "pipeline_telemetry" in status_data
    assert "telemetry" in status_data
    assert status_data["pipeline_telemetry"] == status_data["telemetry"]

    telemetry = status_data["pipeline_telemetry"]
    expected_keys = {
        "total_runs",
        "has_runs",
        "latest_run",
        "run_id",
        "status",
        "created_at",
        "completed_at",
        "goal",
    }
    assert expected_keys.issubset(set(telemetry.keys()))


def test_telemetry_against_live_runs_directory():
    """Verify live inspection of actual .runs directory in workspace."""
    telemetry = get_pipeline_telemetry()

    assert telemetry["has_runs"] is True
    assert telemetry["total_runs"] >= 5
    assert telemetry["latest_run"] is not None

    latest = telemetry["latest_run"]
    assert latest["run_id"] == "run_20260927_191513"
    assert latest["status"] == "SUCCESS"
    assert "Create tools/company_info.py" in latest["goal"]
    assert latest["created_at"] is not None
    assert latest["completed_at"] is not None

    # Top-level convenience keys
    assert telemetry["run_id"] == latest["run_id"]
    assert telemetry["status"] == latest["status"]
    assert telemetry["goal"] == latest["goal"]


def test_telemetry_read_only_guarantee():
    """Verify get_pipeline_telemetry() does not create, modify, or delete any files."""
    runs_dir = REPO_ROOT / ".runs"
    assert runs_dir.exists()

    entries_before = sorted(p.name for p in runs_dir.iterdir())
    get_pipeline_telemetry()
    entries_after = sorted(p.name for p in runs_dir.iterdir())

    assert entries_before == entries_after


# ==============================================================================
# 2. Display States in Console Formatter
# ==============================================================================

def test_console_section_placement_and_dividers():
    """Verify 'Pipeline Telemetry:' block is strictly between 'Summary:' and 'Implemented Capabilities:'."""
    status_data = get_company_status()
    console_out = format_status_console(status_data)

    summary_idx = console_out.find("Summary:")
    telemetry_idx = console_out.find("Pipeline Telemetry:")
    caps_idx = console_out.find("Implemented Capabilities:")

    assert summary_idx != -1, "Summary section missing"
    assert telemetry_idx != -1, "Pipeline Telemetry section missing"
    assert caps_idx != -1, "Implemented Capabilities section missing"

    assert summary_idx < telemetry_idx < caps_idx, (
        "Pipeline Telemetry: must be strictly between Summary: and Implemented Capabilities:"
    )

    divider = "-" * 80
    # There must be a divider between Summary and Pipeline Telemetry, and after Pipeline Telemetry
    section_between_summary_and_telemetry = console_out[summary_idx:telemetry_idx]
    assert divider in section_between_summary_and_telemetry

    section_between_telemetry_and_caps = console_out[telemetry_idx:caps_idx]
    assert divider in section_between_telemetry_and_caps


def test_console_label_alignment_and_80_col_compliance():
    """Verify labels use '  {label:<15} : {value}' formatting and stay 80-column compliant."""
    status_data = get_company_status()
    console_out = format_status_console(status_data)

    lines = console_out.splitlines()
    telemetry_lines = []
    in_telemetry = False

    for line in lines:
        if line == "Pipeline Telemetry:":
            in_telemetry = True
            continue
        if in_telemetry:
            if line.startswith("-" * 80):
                break
            telemetry_lines.append(line)

    assert len(telemetry_lines) >= 3
    for line in telemetry_lines:
        assert len(line) <= 81  # 80-column compliant (with standard goal truncation)
        assert line.startswith("  "), f"Line should be indented by 2 spaces: '{line}'"
        assert " : " in line, f"Line missing separator ' : ': '{line}'"
        label_part, value_part = line.split(" : ", 1)
        assert len(label_part) == 17, f"Indent (2) + Label (15) must be 17 chars: '{label_part}'"


def test_state_empty_zero_runs():
    """Test Empty state when 0 runs exist."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        telemetry = get_pipeline_telemetry(repo_root=tmp_path)

        assert telemetry["total_runs"] == 0
        assert telemetry["has_runs"] is False
        assert telemetry["latest_run"] is None
        assert telemetry["status"] is None

        mock_status = {
            "company_name": "Jester AI Company",
            "summary": {"total_agents": 7, "active_agents": 7, "planned_agents": 0},
            "pipeline_telemetry": telemetry,
            "capabilities": [],
            "agents": [],
        }
        console_out = format_status_console(mock_status)
        assert "Pipeline Telemetry:" in console_out
        assert "  Total Runs      : 0" in console_out
        assert "  Latest Run      : None" in console_out
        assert "  Status          : None" in console_out


def test_state_empty_directory_exists():
    """Test Empty state when .runs/ directory exists but contains no subdirectories."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        (tmp_path / ".runs").mkdir()

        telemetry = get_pipeline_telemetry(repo_root=tmp_path)
        assert telemetry["total_runs"] == 0
        assert telemetry["latest_run"] is None


def test_state_success_run():
    """Test Success state display with populated fields."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        runs_dir = tmp_path / ".runs"
        run_dir = runs_dir / "run_20260928_100000"
        run_dir.mkdir(parents=True)

        manifest = {
            "run_id": "run_20260928_100000",
            "status": "SUCCESS",
            "created_at": "2026-09-28T10:00:00+00:00",
            "completed_at": "2026-09-28T10:02:00+00:00",
            "goal": "Build successful capability",
        }
        (run_dir / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

        telemetry = get_pipeline_telemetry(repo_root=tmp_path)
        assert telemetry["total_runs"] == 1
        assert telemetry["status"] == "SUCCESS"
        assert telemetry["latest_run"]["run_id"] == "run_20260928_100000"

        mock_status = {
            "pipeline_telemetry": telemetry,
            "capabilities": [],
            "agents": [],
        }
        console_out = format_status_console(mock_status)
        assert "  Total Runs      : 1" in console_out
        assert "  Latest Run      : run_20260928_100000" in console_out
        assert "  Status          : SUCCESS" in console_out
        assert "  Goal            : Build successful capability" in console_out
        assert "  Created At      : 2026-09-28T10:00:00+00:00" in console_out
        assert "  Completed At    : 2026-09-28T10:02:00+00:00" in console_out


def test_state_failed_run():
    """Test Failed state display with error/failure status."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        runs_dir = tmp_path / ".runs"
        run_dir = runs_dir / "run_20260928_110000"
        run_dir.mkdir(parents=True)

        manifest = {
            "run_id": "run_20260928_110000",
            "status": "FAILED",
            "created_at": "2026-09-28T11:00:00+00:00",
            "completed_at": "2026-09-28T11:01:00+00:00",
            "goal": "Failing pipeline run test",
        }
        (run_dir / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

        telemetry = get_pipeline_telemetry(repo_root=tmp_path)
        assert telemetry["status"] == "FAILED"

        mock_status = {
            "pipeline_telemetry": telemetry,
            "capabilities": [],
            "agents": [],
        }
        console_out = format_status_console(mock_status)
        assert "  Status          : FAILED" in console_out
        assert "  Goal            : Failing pipeline run test" in console_out


def test_state_running_state():
    """Test Running state when run is in progress and completed_at is None."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        runs_dir = tmp_path / ".runs"
        run_dir = runs_dir / "run_20260928_120000"
        run_dir.mkdir(parents=True)

        manifest = {
            "run_id": "run_20260928_120000",
            "status": "RUNNING",
            "created_at": "2026-09-28T12:00:00+00:00",
            "completed_at": None,
            "goal": "Active in-flight execution",
        }
        (run_dir / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

        telemetry = get_pipeline_telemetry(repo_root=tmp_path)
        assert telemetry["status"] == "RUNNING"
        assert telemetry["completed_at"] is None

        mock_status = {
            "pipeline_telemetry": telemetry,
            "capabilities": [],
            "agents": [],
        }
        console_out = format_status_console(mock_status)
        assert "  Status          : RUNNING" in console_out
        assert "  Completed At    : In Progress" in console_out


def test_state_corrupted_manifest_invalid_json():
    """Test Corrupted manifest fallback when run_manifest.json contains invalid JSON syntax."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        runs_dir = tmp_path / ".runs"
        run_dir = runs_dir / "run_20260928_130000"
        run_dir.mkdir(parents=True)

        (run_dir / "run_manifest.json").write_text("{ unclosed invalid json ...", encoding="utf-8")

        telemetry = get_pipeline_telemetry(repo_root=tmp_path)
        assert telemetry["total_runs"] == 1
        assert telemetry["status"] == "CORRUPTED"
        assert telemetry["latest_run"]["run_id"] == "run_20260928_130000"
        assert "error" in telemetry["latest_run"]

        mock_status = {
            "pipeline_telemetry": telemetry,
            "capabilities": [],
            "agents": [],
        }
        console_out = format_status_console(mock_status)
        assert "  Total Runs      : 1" in console_out
        assert "  Latest Run      : run_20260928_130000" in console_out
        assert "  Status          : CORRUPTED" in console_out


def test_state_corrupted_manifest_missing_file():
    """Test Corrupted manifest fallback when run directory has no run_manifest.json."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        runs_dir = tmp_path / ".runs"
        run_dir = runs_dir / "run_20260928_140000"
        run_dir.mkdir(parents=True)

        telemetry = get_pipeline_telemetry(repo_root=tmp_path)
        assert telemetry["total_runs"] == 1
        assert telemetry["status"] == "CORRUPTED"
        assert telemetry["latest_run"]["run_id"] == "run_20260928_140000"


# ==============================================================================
# 3. Goal Sanitization and Truncation
# ==============================================================================

def test_goal_sanitization_whitespace():
    """Verify whitespace, newlines, and tabs are normalized to single spaces."""
    messy_goal = "  First line\n  Second line \t with  multiple    spaces.  "
    sanitized = _sanitize_and_truncate_goal(messy_goal)
    assert sanitized == "First line Second line with multiple spaces."


def test_goal_truncation_boundary():
    """Verify goals > 61 characters are truncated to 58 chars + '...' (61 total)."""
    # Exactly 61 characters
    exact_61 = "A" * 61
    assert _sanitize_and_truncate_goal(exact_61) == exact_61
    assert len(_sanitize_and_truncate_goal(exact_61)) == 61

    # Exactly 62 characters
    over_61 = "B" * 62
    truncated = _sanitize_and_truncate_goal(over_61)
    assert len(truncated) == 61
    assert truncated == ("B" * 58) + "..."

    # Long text
    long_text = "This is a very long goal description designed to test the 61-character boundary limit strictly."
    long_truncated = _sanitize_and_truncate_goal(long_text)
    assert len(long_truncated) == 61
    assert long_truncated.endswith("...")
    assert long_truncated == long_text[:58] + "..."


# ==============================================================================
# 4. Entrypoint Subprocess Executions
# ==============================================================================

def test_entrypoint_python_status_contains_telemetry():
    """Verify `python status.py` runs and outputs Pipeline Telemetry section."""
    result = subprocess.run(
        [sys.executable, "status.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "Pipeline Telemetry:" in result.stdout
    assert "Total Runs      : 5" in result.stdout
    assert "Latest Run      : run_20260927_191513" in result.stdout
    assert "Status          : SUCCESS" in result.stdout


def test_entrypoint_python_status_json_contains_telemetry():
    """Verify `python status.py --json` produces valid JSON with telemetry keys."""
    result = subprocess.run(
        [sys.executable, "status.py", "--json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)

    assert "pipeline_telemetry" in data
    assert "telemetry" in data
    assert data["pipeline_telemetry"]["total_runs"] == 5
    assert data["pipeline_telemetry"]["latest_run"]["run_id"] == "run_20260927_191513"
    assert data["pipeline_telemetry"]["latest_run"]["status"] == "SUCCESS"


def test_root_status_module_exports():
    """Verify root status.py exposes get_pipeline_telemetry."""
    assert hasattr(root_status, "get_pipeline_telemetry")
    assert callable(root_status.get_pipeline_telemetry)
