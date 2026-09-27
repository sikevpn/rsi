"""Independent Auditor — the second line of defence against false completion.

Report §5.2 ② / §6 stage 2: a *separate* agent session that is instructed to disbelieve
the executor, must actually run the test suite and paste its output, and returns a
binary verdict.  Two rules are enforced mechanically rather than by prompt discipline:

1. The orchestrator re-runs the backpressure commands itself and compares the result
   against whatever ``DONE.json`` claims.  A mismatch is recorded as a cheat.
2. The auditor's verdict is read only from ``AUDIT.json`` — never from its stdout
   (report §5.3: "完成信号只认文件").
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .backend import AgentRequest, Backend

__all__ = [
    "AuditVerdict",
    "Auditor",
    "run_commands",
    "CommandResult",
    "count_tests",
    "SUSPICIOUS_MARKERS",
]

_COLLECTED_RE = re.compile(r"(\d+)\s+tests?\s+collected")

#: Markers that let a suite "pass" without asserting anything.
SUSPICIOUS_MARKERS: tuple[str, ...] = (
    "@pytest.mark.skip",
    "@pytest.mark.xfail",
    "pytest.skip(",
    "unittest.skip",
)


@dataclass
class CommandResult:
    command: str
    exit_code: int
    output: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


def count_tests(command: str, cwd: str | Path, timeout_s: float = 300.0) -> int | None:
    """Collect-only test count, or None when it cannot be determined.

    Used by the "防测试净减少守卫" the report lists under 防自欺.
    """
    result = run_commands([command], cwd, timeout_s)
    if not result or result[0].exit_code != 0:
        return None
    match = _COLLECTED_RE.search(result[0].output)
    return int(match.group(1)) if match else None


def run_commands(
    commands: Sequence[str], cwd: str | Path, timeout_s: float = 900.0
) -> list[CommandResult]:
    """Run backpressure commands sequentially, stopping at the first failure."""
    results: list[CommandResult] = []
    for command in commands:
        try:
            proc = subprocess.run(  # noqa: S603 - commands come from config, not from the agent
                command,
                shell=True,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
            code, out = proc.returncode, (proc.stdout or "") + (proc.stderr or "")
        except subprocess.TimeoutExpired:
            code, out = 124, f"timed out after {timeout_s}s"
        except OSError as exc:
            code, out = 127, str(exc)
        results.append(CommandResult(command=command, exit_code=code, output=out[-4000:]))
        if code != 0:
            break
    return results


@dataclass
class AuditVerdict:
    passed: bool
    reasons: tuple[str, ...]
    test_exit_code: int | None
    test_output: str
    audit_file_seen: bool

    def explain(self) -> str:
        head = "PASS" if self.passed else "FAIL"
        return f"{head}: " + ("; ".join(self.reasons) if self.reasons else "no objections")


class Auditor:
    def __init__(
        self,
        backend: Backend,
        test_commands: Sequence[str],
        prompt_template: str = "",
        timeout_s: float = 900.0,
        audit_file: str = "AUDIT.json",
        count_command: str | None = None,
        baseline_test_count: int | None = None,
        test_globs: Sequence[str] = ("test_*.py", "tests/**/*.py"),
    ) -> None:
        self.backend = backend
        self.test_commands = tuple(test_commands)
        self.prompt_template = prompt_template
        self.timeout_s = timeout_s
        self.audit_file = audit_file
        self.count_command = count_command
        self.baseline_test_count = baseline_test_count
        self.test_globs = tuple(test_globs)

    def _scan_for_suppressed_tests(self, root: Path) -> list[str]:
        found: list[str] = []
        for glob in self.test_globs:
            for path in sorted(root.glob(glob)):
                if not path.is_file():
                    continue
                try:
                    body = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for marker in SUSPICIOUS_MARKERS:
                    if marker in body:
                        found.append(f"{path.name} contains {marker!r}")
        return found

    def review(
        self,
        cwd: str | Path,
        task_text: str,
        claimed_files: Sequence[str] = (),
        claimed_exit_code: int | None = None,
    ) -> AuditVerdict:
        root = Path(cwd)
        reasons: list[str] = []

        # 1. The auditor runs the suite itself.  This is the part a lying worker cannot fake.
        results = run_commands(self.test_commands, root, self.timeout_s)
        test_code = results[-1].exit_code if results else None
        test_output = "\n".join(r.output for r in results)[-4000:]
        if test_code != 0:
            reasons.append(f"independent test run failed with exit code {test_code}")

        # 2. Claimed changes must actually exist on disk.
        for rel in claimed_files:
            target = root / rel
            if not target.exists():
                reasons.append(f"claimed change {rel} does not exist on disk")
            elif target.is_file() and target.stat().st_size == 0:
                reasons.append(f"claimed change {rel} is empty")

        # 3. Declaration vs. measurement.
        if claimed_exit_code is not None and test_code is not None:
            if int(claimed_exit_code) != int(test_code):
                reasons.append(
                    f"DONE.json claims test_exit_code={claimed_exit_code} but an "
                    f"independent run returned {test_code}"
                )

        # 3b. Net-decrease guard: a suite that shrinks or is silenced is not progress.
        if self.count_command:
            current = count_tests(self.count_command, root, self.timeout_s)
            if current is None:
                reasons.append("could not collect a test count to compare against baseline")
            elif self.baseline_test_count is not None and current < self.baseline_test_count:
                reasons.append(
                    f"test count dropped from {self.baseline_test_count} to {current} "
                    "(net-decrease guard)"
                )
        reasons.extend(self._scan_for_suppressed_tests(root))

        # 4. Second-opinion agent, verdict read from a file only.
        audit_path = root / self.audit_file
        if audit_path.exists():
            audit_path.unlink()
        prompt = (self.prompt_template or "Review the change.").replace(
            "{task}", task_text
        ).replace("{test_output}", test_output[-2000:])
        self.backend.run(
            AgentRequest(
                mode="audit",
                prompt=prompt,
                cwd=root,
                task=task_text,
                context=(test_output[-2000:],),
            )
        )
        seen = audit_path.exists()
        if not seen:
            reasons.append(f"auditor wrote no {self.audit_file}; refusing to trust stdout")
        else:
            try:
                data = json.loads(audit_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                data = {}
                reasons.append(f"{self.audit_file} is not valid JSON: {exc}")
            verdict = str(data.get("verdict", "")).lower()
            if verdict not in {"pass", "ok", "approve"}:
                objection = data.get("reason") or data.get("reasons") or "unspecified"
                reasons.append(f"auditor verdict was {verdict!r}: {objection}")

        return AuditVerdict(
            passed=not reasons,
            reasons=tuple(reasons),
            test_exit_code=test_code,
            test_output=test_output,
            audit_file_seen=seen,
        )
