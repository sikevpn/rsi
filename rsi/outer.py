"""Outer loop — the high-frequency task-execution layer (report §5.2 ①, §6 stages 1–2).

Control flow, verbatim from report §5.5:

    read IMPLEMENTATION_PLAN.md -> pick the first open item -> spawn a fresh-context
    worker -> run backpressure -> on success tick the checkbox and snapshot -> next

Four guardrails plus a kill switch are enforced here (report §3.3):
``max_iterations``, consecutive-failure cutoff, thrashing detection, ``max_cost_usd``,
and the ``LOOP_PAUSED`` file marker.  Exit codes follow the ralph-orchestrator
convention the report cites: 0 done / 1 failed / 2 limit / 3 external stop.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import blackboard
from .audit import AuditVerdict, Auditor, count_tests, run_commands
from .backend import AgentRequest, Backend
from .config import LoopConfig
from .gate import Gate
from .receipts import Receipt, append_receipt
from .vcs import NoopVCS, VCS

__all__ = [
    "EXIT_OK",
    "EXIT_FAILED",
    "EXIT_LIMIT",
    "EXIT_KILL_SWITCH",
    "TaskOutcome",
    "RunSummary",
    "OuterLoop",
]

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_LIMIT = 2
EXIT_KILL_SWITCH = 3


@dataclass
class TaskOutcome:
    task_id: str
    task_text: str
    terminal_state: str
    iterations: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    test_pass: bool = False
    failure_signature: str = ""
    cheat_detected: bool = False
    notes: str = ""
    audit_reasons: tuple[str, ...] = ()

    def to_receipt(self) -> Receipt:
        return Receipt(
            task=f"{self.task_id}: {self.task_text}",
            terminal_state=self.terminal_state,
            iterations=self.iterations,
            tokens=self.tokens,
            cost_usd=round(self.cost_usd, 6),
            test_pass=self.test_pass,
            verdict="pass" if self.test_pass else "fail",
            failure_signature=self.failure_signature,
            notes=self.notes,
            next_step="" if self.terminal_state == "COMPLETED" else self.failure_signature,
            evidence={
                "cheat_detected": self.cheat_detected,
                "audit_reasons": list(self.audit_reasons),
            },
        )


@dataclass
class RunSummary:
    outcomes: list[TaskOutcome] = field(default_factory=list)
    terminal_state: str = "NO_TASKS"
    exit_code: int = EXIT_OK
    total_cost_usd: float = 0.0
    total_tokens: int = 0
    receipts_path: Path | None = None

    @property
    def completed(self) -> int:
        return sum(1 for o in self.outcomes if o.terminal_state == "COMPLETED")


class OuterLoop:
    def __init__(
        self,
        project_root: str | Path,
        backend: Backend,
        config: LoopConfig | None = None,
        gate: Gate | None = None,
        vcs: VCS | None = None,
        auditor: Auditor | None = None,
        prompts: dict[str, str] | None = None,
        on_iteration: Callable[[TaskOutcome], None] | None = None,
    ) -> None:
        self.root = Path(project_root)
        self.backend = backend
        self.config = config or LoopConfig()
        self.gate = gate or Gate()
        self.vcs = vcs or NoopVCS()
        self.auditor = auditor
        self.prompts = prompts if prompts is not None else self._load_prompts()
        self.on_iteration = on_iteration
        self.baseline_test_count: int | None = None

    # ------------------------------------------------------------- plumbing

    def _load_prompts(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for mode in ("plan", "build", "audit", "meta"):
            path = self.root / self.config.prompt_path(mode)
            if path.exists():
                out[mode] = path.read_text(encoding="utf-8")
        return out

    def _prompt(self, mode: str, task: blackboard.Task, iteration: int, memories: str) -> str:
        template = self.prompts.get(mode, f"You are in {mode} mode.\n")
        return (
            template.replace("{task}", task.text)
            .replace("{iteration}", str(iteration))
            .replace("{memories}", memories or "(no memories yet)")
        )

    def _kill_switch_engaged(self) -> bool:
        return (self.root / self.config.kill_switch_file).exists()

    def _read_done(self) -> dict | None:
        """Completion signal is read *only* from the file (report §5.3)."""
        path = self.root / self.config.done_file
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        return data if isinstance(data, dict) else None

    def _clear_signals(self) -> None:
        """A fresh-context turn must not inherit the previous turn's completion signal."""
        for name in (self.config.done_file, self.config.audit_file):
            path = self.root / name
            if path.exists():
                path.unlink()

    # ---------------------------------------------------------------- task

    def _run_task(self, task: blackboard.Task) -> TaskOutcome:
        cfg = self.config
        tokens = 0
        cost = 0.0
        iterations = 0
        consecutive = 0
        signatures: Counter[str] = Counter()
        cheat = False
        last_sig = ""
        audit_reasons: tuple[str, ...] = ()
        notes = ""

        def outcome(state: str, test_pass: bool = False) -> TaskOutcome:
            return TaskOutcome(
                task_id=task.id,
                task_text=task.text,
                terminal_state=state,
                iterations=iterations,
                tokens=tokens,
                cost_usd=cost,
                test_pass=test_pass,
                failure_signature="" if state == "COMPLETED" else last_sig,
                cheat_detected=cheat,
                notes=notes,
                audit_reasons=audit_reasons,
            )

        for iteration in range(1, cfg.max_iterations + 1):
            iterations = iteration
            if self._kill_switch_engaged():
                notes = "kill switch file present"
                return outcome("KILL_SWITCH")

            self._clear_signals()
            memories = blackboard.load_memories(
                self.root / cfg.memories_file, cfg.memory_max_chars
            )
            result = self.backend.run(
                AgentRequest(
                    mode="build",
                    prompt=self._prompt("build", task, iteration, memories),
                    cwd=self.root,
                    task=task.text,
                    iteration=iteration,
                    context=(memories,) if memories else (),
                )
            )
            tokens += result.tokens
            cost += result.cost_usd

            if result.spawn_error:
                last_sig = "BACKEND_ERROR"
                notes = result.spawn_error
                return outcome("BACKEND_ERROR")

            done = self._read_done()
            if done is None:
                last_sig = "NO_DONE_SIGNAL"
                notes = "worker produced no valid DONE.json"
            else:
                results = run_commands(cfg.test_commands, self.root, cfg.timeout_s)
                actual = results[-1].exit_code if results else None
                claimed = done.get("test_exit_code")

                if claimed is not None and actual is not None and int(claimed) != int(actual):
                    cheat = True
                    last_sig = "CLAIM_MISMATCH"
                    notes = (
                        f"DONE.json claims test_exit_code={claimed}; independent run "
                        f"returned {actual}"
                    )
                elif actual != 0:
                    last_sig = "TEST_FAIL"
                    notes = (results[-1].output if results else "")[-500:]
                else:
                    verdict: AuditVerdict | None = None
                    if cfg.auditor_enabled and self.auditor is not None:
                        verdict = self.auditor.review(
                            cwd=self.root,
                            task_text=task.text,
                            claimed_files=tuple(done.get("files_changed") or ()),
                            claimed_exit_code=claimed if claimed is not None else actual,
                        )
                        audit_reasons = verdict.reasons
                    if verdict is not None and not verdict.passed:
                        last_sig = "AUDIT_FAIL"
                        notes = "; ".join(verdict.reasons)[:500]
                    else:
                        blackboard.mark_done(self.root / cfg.plan_file, task.id)
                        self.vcs.snapshot(f"task {task.id}: {task.text}")
                        return outcome("COMPLETED", test_pass=True)

            # ---- failure bookkeeping ----
            signatures[last_sig] += 1
            consecutive += 1
            if self.on_iteration is not None:
                self.on_iteration(outcome("FAILED"))
            if signatures[last_sig] >= cfg.thrashing_threshold:
                notes = f"signature {last_sig!r} repeated {signatures[last_sig]}x"
                return outcome("STALEMATE")
            if consecutive >= cfg.max_consecutive_failures:
                state = "AUDIT_REJECTED" if last_sig == "AUDIT_FAIL" else "CONSECUTIVE_FAILURES"
                return outcome(state)

        notes = f"hit max_iterations={cfg.max_iterations}"
        return outcome("ITERATION_LIMIT")

    # ----------------------------------------------------------------- run

    def run(self) -> RunSummary:
        cfg = self.config
        summary = RunSummary(receipts_path=self.root / cfg.receipts_file)

        if self._kill_switch_engaged():
            summary.terminal_state = "KILL_SWITCH"
            summary.exit_code = EXIT_KILL_SWITCH
            return summary

        plan_path = self.root / cfg.plan_file
        if not plan_path.exists():
            summary.terminal_state = "FAILED"
            summary.exit_code = EXIT_FAILED
            return summary

        # Freeze the test-count baseline *before* any worker touches the tree, so the
        # auditor's net-decrease guard has something honest to compare against.
        if cfg.count_command:
            self.baseline_test_count = count_tests(cfg.count_command, self.root, cfg.timeout_s)
            if self.auditor is not None:
                self.auditor.baseline_test_count = self.baseline_test_count

        pending = blackboard.open_tasks(blackboard.parse_plan(plan_path.read_text(encoding="utf-8")))
        if not pending:
            summary.terminal_state = "NO_TASKS"
            summary.exit_code = EXIT_OK
            return summary
        if cfg.max_tasks > 0:
            pending = pending[: cfg.max_tasks]

        kill_hit = False
        budget_hit = False
        worst = "COMPLETED"

        for task in pending:
            if self._kill_switch_engaged():
                kill_hit = True
                break
            result = self._run_task(task)
            summary.outcomes.append(result)
            append_receipt(summary.receipts_path, result.to_receipt())  # type: ignore[arg-type]
            summary.total_cost_usd = round(summary.total_cost_usd + result.cost_usd, 6)
            summary.total_tokens += result.tokens

            if result.terminal_state != "COMPLETED":
                worst = result.terminal_state

            if result.terminal_state == "KILL_SWITCH":
                kill_hit = True
                break
            if result.terminal_state == "BACKEND_ERROR":
                budget_hit = True  # environmental: retrying cannot help
                break
            if summary.total_cost_usd >= cfg.max_cost_usd:
                budget_hit = True
                break

        if kill_hit:
            summary.terminal_state = "KILL_SWITCH"
            summary.exit_code = EXIT_KILL_SWITCH
        elif budget_hit:
            summary.terminal_state = worst if worst != "COMPLETED" else "BUDGET_EXHAUSTED"
            summary.exit_code = EXIT_LIMIT
        elif worst != "COMPLETED":
            summary.terminal_state = worst
            summary.exit_code = EXIT_FAILED
        else:
            summary.terminal_state = "COMPLETED"
            summary.exit_code = EXIT_OK
        return summary
