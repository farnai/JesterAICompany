"""Antigravity CLI runtime adapter for Jester AI Company.

Provides a clean, bounded execution boundary connecting Python code to the
Antigravity (`agy`) CLI runtime for individual agent execution.

Architecture:
    Python Caller
          ↓
    AntigravityRuntime.execute(agent=..., prompt=...)
          ↓
    agy.exe subprocess (argument array, NO shell=True)
          ↓
    Subagent (e.g. .agents/agents/ceo/agent.md)
          ↓
    AgentExecutionResult (structured output, exit code, duration, logs)
"""

from dataclasses import asdict, dataclass, field
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

from .registry import RECOGNIZED_AGENTS


class AntigravityRuntimeError(Exception):
    """Base exception for Antigravity runtime adapter errors."""
    pass


class InvalidAgentError(AntigravityRuntimeError, ValueError):
    """Raised when an unapproved or unrecognized agent role is requested."""
    pass


def kill_process_tree(pid: int) -> None:
    """Safely terminate a process and all of its child processes across platforms."""
    if not pid or pid <= 0:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            import signal
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except Exception:
                try:
                    os.kill(pid, signal.SIGKILL)
                except Exception:
                    pass
    except Exception as exc:
        logger.warning("Failed to terminate process tree for PID %s: %s", pid, exc)


@dataclass
class AgentExecutionResult:
    """Structured outcome of an Antigravity agent CLI execution."""
    agent: str
    success: bool
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: float
    timed_out: bool = False
    command: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize result to a dictionary."""
        return asdict(self)


class AntigravityRuntime:
    """Runtime adapter executing Antigravity subagents via the agy CLI.

    Responsible strictly for:
    - locating the absolute repository root
    - validating agent roles against registered company agents
    - constructing the verified agy command
    - invoking the agy executable via argument array (NO shell=True)
    - capturing stdout, stderr, exit code, and execution duration
    - enforcing timeout boundaries
    - returning structured AgentExecutionResult objects

    This adapter is NOT responsible for:
    - task routing, planning, or delegation
    - business logic or state transitions
    - QA verification or retry loops
    """

    def __init__(
        self,
        repo_root: Optional[Path] = None,
        default_timeout: float = 600.0,
    ):
        self.repo_root = (repo_root or Path(__file__).resolve().parent.parent).resolve()
        self.default_timeout = max(1.0, float(default_timeout))
        self._valid_roles: Set[str] = {agent["role"].lower() for agent in RECOGNIZED_AGENTS}

    @property
    def valid_roles(self) -> Set[str]:
        """Return the set of recognized agent roles."""
        return set(self._valid_roles)

    def validate_agent(self, agent: str) -> str:
        """Validate that the requested agent is a registered Jester AI Company agent.

        Args:
            agent: The role identifier (e.g. 'ceo', 'developer').

        Returns:
            Normalized lowercase agent role string.

        Raises:
            InvalidAgentError: If agent is empty, not recognized, or missing agent.md.
        """
        if not agent or not isinstance(agent, str):
            raise InvalidAgentError("Agent name must be a non-empty string.")

        normalized = agent.strip().lower()
        if normalized not in self._valid_roles:
            raise InvalidAgentError(
                f"Invalid agent '{agent}'. Must be one of registered roles: {sorted(self._valid_roles)}"
            )

        agent_md = self.repo_root / ".agents" / "agents" / normalized / "agent.md"
        if not agent_md.is_file():
            raise InvalidAgentError(
                f"Agent definition file not found for '{normalized}' at '{agent_md}'"
            )

        return normalized

    def build_command(
        self,
        agent: str,
        prompt: str,
        workspace_dir: Optional[Path] = None,
    ) -> List[str]:
        """Construct the verified agy command argument array.

        IMPORTANT SECURITY NOTE:
        '--dangerously-skip-permissions' is temporarily allowed ONLY because this
        is a local development runtime milestone. It must NOT become the production
        permission model. Formal permissions and access boundaries remain tracked as
        deferred capabilities in BACKLOG.md.

        The executable is strictly 'agy'; user input cannot alter binary or flags.
        """
        validated_agent = self.validate_agent(agent)
        cleaned_prompt = (prompt or "").strip()
        if not cleaned_prompt:
            raise ValueError("Prompt must not be empty.")

        max_cli_prompt_len = 28000
        if len(cleaned_prompt) > max_cli_prompt_len:
            cleaned_prompt = cleaned_prompt[:max_cli_prompt_len]

        target_workspace = (
            Path(workspace_dir).resolve() if workspace_dir is not None else self.repo_root
        )

        return [
            "agy",
            "--add-dir",
            str(target_workspace),
            "--agent",
            validated_agent,
            "--dangerously-skip-permissions",
            "-p",
            cleaned_prompt,
        ]

    def execute(
        self,
        agent: str,
        prompt: str,
        timeout: Optional[float] = None,
        workspace_dir: Optional[Path] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> AgentExecutionResult:
        """Execute a validated agent prompt through the Antigravity CLI runtime.

        Args:
            agent: Recognized agent role name (e.g. 'ceo').
            prompt: Text prompt instruction for the agent.
            timeout: Optional maximum seconds to wait before aborting (defaults to self.default_timeout).
            workspace_dir: Optional isolated workspace directory (e.g. detached worktree).
            env: Optional sanitized environment dictionary for child process execution.

        Returns:
            AgentExecutionResult containing stdout, stderr, exit code, duration, and success flag.
        """
        validated_agent = self.validate_agent(agent)
        cmd = self.build_command(validated_agent, prompt, workspace_dir=workspace_dir)
        exec_timeout = float(timeout) if timeout is not None else self.default_timeout
        target_cwd = (
            str(workspace_dir.resolve()) if workspace_dir is not None else str(self.repo_root)
        )

        max_transient_retries = 2
        for attempt in range(max_transient_retries + 1):
            start_time = time.perf_counter()
            proc = None
            try:
                # Strictly NO shell=True; invoked as argument array
                proc = subprocess.Popen(
                    cmd,
                    cwd=target_cwd,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    shell=False,
                )
                try:
                    stdout_str, stderr_str = proc.communicate(timeout=exec_timeout)
                    exit_code = proc.returncode
                except subprocess.TimeoutExpired as exc:
                    kill_process_tree(proc.pid)
                    try:
                        out_b, err_b = proc.communicate(timeout=3.0)
                        stdout_str = (exc.output or "") + (out_b or "")
                        stderr_str = (exc.stderr or "") + (err_b or "")
                    except Exception:
                        stdout_str = exc.output or ""
                        stderr_str = exc.stderr or ""

                    # Bounded diagnostic output
                    if len(stdout_str) > 4000:
                        stdout_str = "...[truncated]...\n" + stdout_str[-4000:]
                    if len(stderr_str) > 4000:
                        stderr_str = "...[truncated]...\n" + stderr_str[-4000:]

                    duration_ms = (time.perf_counter() - start_time) * 1000.0
                    timeout_msg = f"Agent execution timed out after {exec_timeout:.1f} seconds."
                    full_stderr = f"{stderr_str}\n{timeout_msg}".strip() if stderr_str else timeout_msg

                    return AgentExecutionResult(
                        agent=validated_agent,
                        success=False,
                        stdout=stdout_str,
                        stderr=full_stderr,
                        exit_code=-1,
                        duration_ms=round(duration_ms, 2),
                        timed_out=True,
                        command=cmd,
                    )

                duration_ms = (time.perf_counter() - start_time) * 1000.0

                if exit_code != 0 and attempt < max_transient_retries:
                    combined_err = f"{stdout_str or ''} {stderr_str or ''}".lower()
                    if (
                        "503" in combined_err
                        or "unavailable" in combined_err
                        or "429" in combined_err
                        or "resource_exhausted" in combined_err
                    ):
                        time.sleep(2.0 * (attempt + 1))
                        continue

                return AgentExecutionResult(
                    agent=validated_agent,
                    success=(exit_code == 0),
                    stdout=stdout_str,
                    stderr=stderr_str,
                    exit_code=exit_code,
                    duration_ms=round(duration_ms, 2),
                    timed_out=False,
                    command=cmd,
                )
            except FileNotFoundError as exc:
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                return AgentExecutionResult(
                    agent=validated_agent,
                    success=False,
                    stdout="",
                    stderr=f"Antigravity CLI executable 'agy' not found on system PATH: {exc} (binary={cmd[0]}, cwd={target_cwd}, cmd_len={len(' '.join(cmd))})",
                    exit_code=127,
                    duration_ms=round(duration_ms, 2),
                    timed_out=False,
                    command=cmd,
                )
            except Exception as exc:
                if proc is not None and proc.poll() is None:
                    kill_process_tree(proc.pid)
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                return AgentExecutionResult(
                    agent=validated_agent,
                    success=False,
                    stdout="",
                    stderr=f"Unexpected error executing agent '{validated_agent}': {exc}",
                    exit_code=1,
                    duration_ms=round(duration_ms, 2),
                    timed_out=False,
                    command=cmd,
                )
