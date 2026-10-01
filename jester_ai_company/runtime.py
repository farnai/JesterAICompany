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
from pathlib import Path
import subprocess
import time
from typing import Any, Dict, List, Optional, Set

from .registry import RECOGNIZED_AGENTS


class AntigravityRuntimeError(Exception):
    """Base exception for Antigravity runtime adapter errors."""
    pass


class InvalidAgentError(AntigravityRuntimeError, ValueError):
    """Raised when an unapproved or unrecognized agent role is requested."""
    pass


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
        default_timeout: float = 60.0,
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

    def build_command(self, agent: str, prompt: str) -> List[str]:
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

        return [
            "agy",
            "--add-dir",
            str(self.repo_root),
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
    ) -> AgentExecutionResult:
        """Execute a validated agent prompt through the Antigravity CLI runtime.

        Args:
            agent: Recognized agent role name (e.g. 'ceo').
            prompt: Text prompt instruction for the agent.
            timeout: Optional maximum seconds to wait before aborting (defaults to self.default_timeout).

        Returns:
            AgentExecutionResult containing stdout, stderr, exit code, duration, and success flag.
        """
        validated_agent = self.validate_agent(agent)
        cmd = self.build_command(validated_agent, prompt)
        exec_timeout = float(timeout) if timeout is not None else self.default_timeout

        start_time = time.perf_counter()
        try:
            # Strictly NO shell=True; invoked as argument array
            proc = subprocess.run(
                cmd,
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=exec_timeout,
                shell=False,
            )
            duration_ms = (time.perf_counter() - start_time) * 1000.0

            return AgentExecutionResult(
                agent=validated_agent,
                success=(proc.returncode == 0),
                stdout=proc.stdout,
                stderr=proc.stderr,
                exit_code=proc.returncode,
                duration_ms=round(duration_ms, 2),
                timed_out=False,
                command=cmd,
            )
        except subprocess.TimeoutExpired as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            stdout_str = (
                exc.stdout.decode("utf-8", errors="replace")
                if isinstance(exc.stdout, bytes)
                else (exc.stdout or "")
            )
            stderr_str = (
                exc.stderr.decode("utf-8", errors="replace")
                if isinstance(exc.stderr, bytes)
                else (exc.stderr or "")
            )
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
        except FileNotFoundError:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            return AgentExecutionResult(
                agent=validated_agent,
                success=False,
                stdout="",
                stderr="Antigravity CLI executable 'agy' not found on system PATH.",
                exit_code=127,
                duration_ms=round(duration_ms, 2),
                timed_out=False,
                command=cmd,
            )
        except Exception as exc:
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
