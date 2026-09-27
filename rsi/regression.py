"""Golden-task regression suite and the quality ratchet (report §6 stage 4, H1/H2).

The suite is RSI's measuring stick: a fixed set of tasks re-run before and after every
self-modification.  The ratchet is deliberately asymmetric — a regression is always
reverted, while an *improvement* claim has to clear the higher bar the report sets in H2
(completion rate +≥15% or average iterations −≥10%).

Keeping the optimisation signal separate from the acceptance gate is the anti-overfitting
rule from §7.2: whatever the debrief used to choose an edit cannot also be the evidence
that the edit worked.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field  # noqa: F401  (field used by SuiteResult/GoldenTask)
from pathlib import Path
from typing import Any, Callable, Sequence

from .backend import Backend, StubBackend, StubTurn
from .config import LoopConfig
from .gate import Gate
from .outer import OuterLoop
from .receipts import summarize

__all__ = [
    "GoldenTask",
    "SuiteResult",
    "load_golden_tasks",
    "run_golden_suite",
    "ratchet_decide",
    "RATCHET_DECISIONS",
]

RATCHET_DECISIONS = ("KEEP_IMPROVED", "KEEP_NEUTRAL", "REVERT_REGRESSED")

#: Report H2 thresholds.
IMPROVEMENT_RATE_DELTA = 0.15
IMPROVEMENT_ITERATION_RATIO = 0.10
REGRESSION_RATE_EPSILON = 1e-9
REGRESSION_ITERATION_TOLERANCE = 1e-9


@dataclass(frozen=True)
class GoldenTask:
    id: str
    name: str
    plan: str
    setup: dict[str, str]
    script: tuple[dict[str, Any], ...]
    expect_terminal_state: str = "COMPLETED"
    description: str = ""
    config_overrides: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GoldenTask":
        return cls(
            id=str(data["id"]),
            name=str(data.get("name", data["id"])),
            plan=str(data.get("plan", "- [ ] (T1) task")),
            setup=dict(data.get("setup") or {}),
            script=tuple(data.get("script") or ()),
            expect_terminal_state=str(data.get("expect_terminal_state", "COMPLETED")),
            description=str(data.get("description", "")),
            config_overrides=dict(data.get("config_overrides") or {}),
        )


def load_golden_tasks(directory: str | Path) -> list[GoldenTask]:
    root = Path(directory)
    if not root.exists():
        return []
    tasks: list[GoldenTask] = []
    for path in sorted(root.glob("*.json")):
        tasks.append(GoldenTask.from_dict(json.loads(path.read_text(encoding="utf-8"))))
    return sorted(tasks, key=lambda t: t.id)


@dataclass
class SuiteResult:
    metrics: dict[str, Any]
    per_task: dict[str, str] = field(default_factory=dict)
    mismatches: tuple[str, ...] = ()


def _build_project(task: GoldenTask, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "IMPLEMENTATION_PLAN.md").write_text(task.plan + "\n", encoding="utf-8")
    (dest / "memories.md").write_text("# memories\n", encoding="utf-8")
    (dest / "receipts").mkdir(exist_ok=True)
    for rel, body in task.setup.items():
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")


def run_golden_suite(
    tasks: Sequence[GoldenTask],
    config: LoopConfig,
    workspace: str | Path,
    backend_factory: Callable[[GoldenTask], Backend] | None = None,
    gate: Gate | None = None,
) -> SuiteResult:
    """Run every golden task once and aggregate the receipts."""
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    per_task: dict[str, str] = {}
    mismatches: list[str] = []

    for task in tasks:
        target = workspace / task.id
        if target.exists():
            shutil.rmtree(target)
        _build_project(task, target)

        backend = (
            backend_factory(task)
            if backend_factory is not None
            else StubBackend([StubTurn(**turn) for turn in task.script])
        )
        cfg = LoopConfig.from_dict({**(config.raw or {}), **task.config_overrides})
        cfg.test_commands = config.test_commands
        cfg.auditor_enabled = False
        loop = OuterLoop(target, backend, config=cfg, gate=gate or Gate())
        summary = loop.run()

        state = summary.outcomes[0].terminal_state if summary.outcomes else summary.terminal_state
        per_task[task.id] = state
        if state != task.expect_terminal_state:
            mismatches.append(f"{task.id}: expected {task.expect_terminal_state}, got {state}")
        for outcome in summary.outcomes:
            rows.append(outcome.to_receipt().payload())

    return SuiteResult(metrics=summarize(rows), per_task=per_task, mismatches=tuple(mismatches))


def ratchet_decide(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Compare two suite runs.  Regressions revert; improvements must clear the H2 bar."""
    rate_before = float(before.get("completion_rate", 0.0))
    rate_after = float(after.get("completion_rate", 0.0))
    iter_before = float(before.get("avg_iterations", 0.0))
    iter_after = float(after.get("avg_iterations", 0.0))
    cost_before = float(before.get("total_cost_usd", 0.0))
    cost_after = float(after.get("total_cost_usd", 0.0))

    reasons: list[str] = []
    regressed = False
    if rate_after < rate_before - REGRESSION_RATE_EPSILON:
        regressed = True
        reasons.append(f"completion_rate fell {rate_before:.3f} -> {rate_after:.3f}")
    if iter_after > iter_before + REGRESSION_ITERATION_TOLERANCE:
        regressed = True
        reasons.append(f"avg_iterations rose {iter_before:.2f} -> {iter_after:.2f}")

    improved = False
    if rate_after - rate_before >= IMPROVEMENT_RATE_DELTA:
        improved = True
        reasons.append(
            f"completion_rate +{rate_after - rate_before:.3f} clears the "
            f"{IMPROVEMENT_RATE_DELTA:.0%} bar (H2)"
        )
    if iter_before > 0 and (iter_before - iter_after) / iter_before >= IMPROVEMENT_ITERATION_RATIO:
        improved = True
        reasons.append(
            f"avg_iterations -{(iter_before - iter_after) / iter_before:.1%} clears the "
            f"{IMPROVEMENT_ITERATION_RATIO:.0%} bar (H2)"
        )

    if cost_after > cost_before:
        reasons.append(f"cost rose {cost_before:.4f} -> {cost_after:.4f} USD")

    if regressed:
        decision = "REVERT_REGRESSED"
    elif improved:
        decision = "KEEP_IMPROVED"
    else:
        decision = "KEEP_NEUTRAL"

    return {
        "decision": decision,
        "regressed": regressed,
        "improved": improved,
        "claim_improvement": improved and not regressed,
        "reasons": reasons,
        "before": before,
        "after": after,
    }
