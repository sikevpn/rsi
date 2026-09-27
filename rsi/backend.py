"""Execution-backend adapter layer (report §5.3, §7.1 "抽象 adapter 层").

Everything downstream talks to :class:`Backend`, never to a specific CLI.  That keeps the
orchestrator unbound from ``claude``/``codex`` flag drift — the failure mode the report
documents in ralphex's README ("claude/codex 一改计费/CLI 形态，ralphex 就被迫跟改").

Two implementations ship:

* :class:`CliBackend` — spawns a real headless CLI as a subprocess and recovers its exit
  code (report §5.3: ``claude -p --dangerously-skip-permissions --output-format stream-json``);
* :class:`StubBackend` — a deterministic scripted backend used for verification when no
  model CLI is reachable, so the whole loop stays testable end to end.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, Sequence, runtime_checkable

__all__ = [
    "AgentRequest",
    "TurnResult",
    "Backend",
    "CliBackend",
    "StubBackend",
    "StubTurn",
    "detect_backend",
    "KNOWN_CLIS",
]

#: Candidate backends, most-preferred first (report §5.3).
KNOWN_CLIS: tuple[str, ...] = ("claude", "codex", "opencode", "gemini")


@dataclass(frozen=True)
class AgentRequest:
    """One fresh-context invocation of a worker agent."""

    mode: str                      # "plan" | "build" | "audit" | "meta"
    prompt: str
    cwd: Path
    task: str = ""
    iteration: int = 0
    context: tuple[str, ...] = ()  # injected memories / notes (report §3.4)


@dataclass
class TurnResult:
    ok: bool
    exit_code: int
    stdout: str
    stderr: str
    duration_s: float
    tokens: int
    cost_usd: float
    backend: str
    spawn_error: str = ""
    script_exhausted: bool = False


@runtime_checkable
class Backend(Protocol):
    name: str

    def run(self, request: AgentRequest) -> TurnResult:  # pragma: no cover - protocol
        ...


@dataclass
class StubTurn:
    """A scripted worker turn."""

    files: dict[str, str] = field(default_factory=dict)
    deletes: tuple[str, ...] = ()
    done: dict | None = None          # written verbatim to DONE.json when not None
    stdout: str = "ok"
    exit_code: int = 0
    tokens: int = 120
    cost_usd: float = 0.01
    spawn_error: str = ""


class StubBackend:
    """Deterministic backend.  Replays a script of :class:`StubTurn` objects."""

    name = "stub"

    def __init__(self, script: Sequence[StubTurn] = ()) -> None:
        self.script: list[StubTurn] = list(script)
        self.calls: list[AgentRequest] = []

    def run(self, request: AgentRequest) -> TurnResult:
        self.calls.append(request)
        started = time.monotonic()

        if not self.script:
            return TurnResult(
                ok=False,
                exit_code=1,
                stdout="",
                stderr="[stub] no script configured",
                duration_s=time.monotonic() - started,
                tokens=0,
                cost_usd=0.0,
                backend=self.name,
                script_exhausted=True,
            )

        exhausted = False
        turn = self.script.pop(0)
        if not self.script:
            exhausted = True

        if turn.spawn_error:
            return TurnResult(
                ok=False,
                exit_code=127,
                stdout="",
                stderr=turn.spawn_error,
                duration_s=time.monotonic() - started,
                tokens=turn.tokens,
                cost_usd=turn.cost_usd,
                backend=self.name,
                spawn_error=turn.spawn_error,
                script_exhausted=exhausted,
            )

        cwd = Path(request.cwd)
        for rel, content in turn.files.items():
            target = cwd / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        for rel in turn.deletes:
            target = cwd / rel
            if target.exists():
                target.unlink()
        if turn.done is not None:
            (cwd / "DONE.json").write_text(
                json.dumps(turn.done, sort_keys=True, ensure_ascii=False), encoding="utf-8"
            )
        elif (cwd / "DONE.json").exists():
            # A fresh-context worker that produced no completion signal must not inherit
            # the previous turn's DONE.json — that is exactly the confabulation the
            # report wants blocked.
            (cwd / "DONE.json").unlink()

        return TurnResult(
            ok=turn.exit_code == 0,
            exit_code=turn.exit_code,
            stdout=turn.stdout,
            stderr="",
            duration_s=time.monotonic() - started,
            tokens=turn.tokens,
            cost_usd=turn.cost_usd,
            backend=self.name,
            script_exhausted=exhausted,
        )


def _extract_usage(stdout: str) -> tuple[int, float]:
    """Best-effort token/cost recovery from stream-json output.  Never fatal."""
    tokens = 0
    cost = 0.0
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        usage = obj.get("usage") if isinstance(obj, dict) else None
        if isinstance(usage, dict):
            tokens += int(usage.get("total_tokens", 0) or 0)
        if isinstance(obj, dict) and "total_cost_usd" in obj:
            try:
                cost = float(obj["total_cost_usd"])
            except (TypeError, ValueError):
                pass
    return tokens, cost


class CliBackend:
    """Spawns a real headless coding CLI and recovers its exit code."""

    def __init__(
        self,
        argv: Sequence[str],
        timeout_s: float = 900.0,
        name: str | None = None,
    ) -> None:
        self.argv: list[str] = list(argv)
        if not self.argv:
            raise ValueError("argv must not be empty")
        self.timeout_s = timeout_s
        self.name = name or Path(self.argv[0]).name

    def run(self, request: AgentRequest) -> TurnResult:
        started = time.monotonic()
        try:
            proc = subprocess.run(  # noqa: S603 - argv is operator-supplied, not user text
                self.argv,
                input=request.prompt,
                cwd=str(request.cwd),
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
                check=False,
            )
        except FileNotFoundError as exc:
            return TurnResult(
                ok=False,
                exit_code=127,
                stdout="",
                stderr=str(exc),
                duration_s=time.monotonic() - started,
                tokens=0,
                cost_usd=0.0,
                backend=self.name,
                spawn_error=f"backend {self.name!r} not found on PATH",
            )
        except subprocess.TimeoutExpired as exc:
            return TurnResult(
                ok=False,
                exit_code=124,
                stdout=(exc.stdout or "") if isinstance(exc.stdout, str) else "",
                stderr=f"timed out after {self.timeout_s}s",
                duration_s=time.monotonic() - started,
                tokens=0,
                cost_usd=0.0,
                backend=self.name,
                spawn_error="timeout",
            )

        tokens, cost = _extract_usage(proc.stdout)
        return TurnResult(
            ok=proc.returncode == 0,
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            duration_s=time.monotonic() - started,
            tokens=tokens,
            cost_usd=cost,
            backend=self.name,
        )


def detect_backend() -> str:
    """Name of the first known CLI on PATH, or ``"none"``."""
    for candidate in KNOWN_CLIS:
        if shutil.which(candidate):
            return candidate
    return "none"
