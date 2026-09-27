"""End-to-end: the two layers closing on each other (report §5.5 control + data flow).

This is the integration test the report's H1 hypothesis needs a harness for: outer loop
produces receipts -> inner loop debriefs and proposes -> the proposal becomes memory ->
the next outer loop reads it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import FIXED_IMPL, TEST_COMMAND

from rsi.backend import StubBackend, StubTurn
from rsi.blackboard import load_memories, parse_plan
from rsi.config import LoopConfig
from rsi.gate import Gate
from rsi.inner import InnerLoop
from rsi.outer import EXIT_OK, OuterLoop
from rsi.receipts import read_receipts, summarize, verify_integrity
from rsi.regression import load_golden_tasks, ratchet_decide, run_golden_suite
from rsi.vcs import NoopVCS

REPO_ROOT = Path(__file__).resolve().parent.parent
SUITE = REPO_ROOT / "golden" / "tasks"
COLLECT = "python3 -m pytest -q --collect-only test_calculator.py"


def honest(task):
    return StubTurn(
        files={"calculator.py": FIXED_IMPL},
        done={
            "status": "done",
            "task": task,
            "files_changed": ["calculator.py"],
            "test_command": TEST_COMMAND,
            "test_exit_code": 0,
            "test_output": "3 passed",
        },
    )


def silent(cost: float = 0.01):
    return StubTurn(files={"calculator.py": FIXED_IMPL}, done=None, cost_usd=cost)


def test_full_two_layer_cycle(project, config):
    """Outer loop -> receipts -> inner loop -> memory -> next outer loop reads it."""
    config.inner_loop_every = 3
    config.min_samples_for_pattern = 3
    config.autonomy_level = "L1"
    config.max_tasks = 3
    config.max_consecutive_failures = 1
    config.thrashing_threshold = 99
    config.auditor_enabled = False

    script = [silent(), silent(), honest("T3")]
    outer = OuterLoop(project, StubBackend(script), config=config)
    summary = outer.run()

    rows = read_receipts(project / "receipts" / "receipts.jsonl")
    assert len(rows) == 3
    assert all(verify_integrity(r) for r in rows)
    assert [r["terminal_state"] for r in rows] == [
        "CONSECUTIVE_FAILURES",
        "CONSECUTIVE_FAILURES",
        "COMPLETED",
    ]
    assert summary.completed == 1

    # inner loop fires on the 3-receipt cadence
    inner = InnerLoop(project, config, Gate.load(project / "gate.yaml"), NoopVCS())
    assert inner.should_trigger() is True
    result = inner.run()

    assert result.debrief.attribution == "EXECUTION_CHOICE"
    assert result.proposal.path == "memories.md"
    assert result.auto_applied is False                  # L1 is report-only
    assert (project / "proposals.md").exists()

    # a human approves: apply the same proposal by hand, then confirm the loop closes
    inner.config.autonomy_level = "L2"
    applied = inner.apply(result.proposal)
    assert applied.applied is True
    assert "DONE.json" in load_memories(project / "memories.md", config.memory_max_chars)

    probe = StubBackend([silent()])
    OuterLoop(project, probe, config=config).run()
    assert "DONE.json" in probe.calls[0].context[0]      # the lesson reached the worker


def test_plan_is_drained_and_exit_code_is_clean(project, config):
    config.max_tasks = 3
    config.auditor_enabled = False
    summary = OuterLoop(
        project, StubBackend([honest("T1"), honest("T2"), honest("T3")]), config=config
    ).run()

    assert summary.exit_code == EXIT_OK
    assert summary.completed == 3
    tasks = parse_plan((project / "IMPLEMENTATION_PLAN.md").read_text(encoding="utf-8"))
    assert all(t.done for t in tasks)


def test_guardrails_hold_over_a_long_run(project, config):
    """Report §6 stage 4 acceptance: no runaway loop, no runaway cost."""
    config.max_tasks = 20
    config.max_iterations = 2
    config.max_consecutive_failures = 2
    config.thrashing_threshold = 99
    config.max_cost_usd = 0.05
    config.auditor_enabled = False

    summary = OuterLoop(
        project, StubBackend([silent(cost=0.01) for _ in range(40)]), config=config
    ).run()

    assert summary.total_cost_usd <= 0.06
    assert summary.exit_code in (1, 2)
    assert len(summary.outcomes) <= 20


def test_ratchet_decision_over_a_real_suite_run(project, config, tmp_path):
    suite_config = LoopConfig()
    suite_config.test_commands = (TEST_COMMAND,)
    tasks = load_golden_tasks(SUITE)

    before = run_golden_suite(tasks, suite_config, tmp_path / "before").metrics
    after_better = {**before, "completion_rate": min(1.0, before["completion_rate"] + 0.2)}
    after_worse = {**before, "completion_rate": max(0.0, before["completion_rate"] - 0.2)}

    assert ratchet_decide(before, after_better)["decision"] == "KEEP_IMPROVED"
    assert ratchet_decide(before, after_worse)["decision"] == "REVERT_REGRESSED"


def test_no_receipt_is_left_unpinned_after_a_mixed_run(project, config):
    config.max_tasks = 3
    config.max_consecutive_failures = 1
    config.thrashing_threshold = 99
    config.auditor_enabled = False
    OuterLoop(
        project,
        StubBackend([honest("T1"), silent(), StubTurn(spawn_error="boom")]),
        config=config,
    ).run()

    rows = read_receipts(project / "receipts" / "receipts.jsonl")
    assert len(rows) == 3
    assert all(verify_integrity(r) for r in rows)
    metrics = summarize(rows)
    assert metrics["runs"] == 3
    assert metrics["completed"] == 1


def test_proposals_file_is_valid_markdown_with_parseable_json_blocks(project, config):
    config.autonomy_level = "L1"
    config.min_samples_for_pattern = 3
    for state, sig in [("FAILED", "NO_DONE_SIGNAL")] * 3:
        from rsi.receipts import Receipt, append_receipt

        append_receipt(
            project / "receipts" / "receipts.jsonl",
            Receipt(task="T1", terminal_state=state, failure_signature=sig),
        )
    InnerLoop(project, config, Gate.load(project / "gate.yaml"), NoopVCS()).run()

    text = (project / "proposals.md").read_text(encoding="utf-8")
    assert text.startswith("# 自改提案")
    blocks = text.split("```json")[1:]
    assert blocks
    for block in blocks:
        payload = json.loads(block.split("```")[0])
        assert payload["attribution"] == "EXECUTION_CHOICE"
        assert payload["diff_lines"] <= config.max_self_diff_lines
