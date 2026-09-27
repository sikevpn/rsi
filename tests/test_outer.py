"""S1 — outer loop: happy path plus one failure injection per guardrail."""

from __future__ import annotations

import json

from conftest import FIXED_IMPL, TEST_COMMAND

from rsi.backend import StubBackend, StubTurn
from rsi.blackboard import parse_plan
from rsi.outer import (
    EXIT_FAILED,
    EXIT_KILL_SWITCH,
    EXIT_LIMIT,
    EXIT_OK,
    OuterLoop,
)
from rsi.receipts import read_receipts, verify_integrity


def fix_turn(task="T1", cost=0.01):
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
        cost_usd=cost,
    )


def silent_turn():
    """Worker edits the tree but never writes DONE.json — no completion signal."""
    return StubTurn(files={"calculator.py": FIXED_IMPL}, done=None)


def test_happy_path_completes_ticks_checkbox_and_writes_receipt(project, config):
    config.max_tasks = 1
    config.auditor_enabled = False
    loop = OuterLoop(project, StubBackend([fix_turn()]), config=config)

    summary = loop.run()

    assert summary.exit_code == EXIT_OK
    assert summary.terminal_state == "COMPLETED"
    assert summary.completed == 1
    assert summary.outcomes[0].test_pass is True

    plan = parse_plan((project / "IMPLEMENTATION_PLAN.md").read_text(encoding="utf-8"))
    assert {t.id: t.done for t in plan}["T1"] is True
    assert {t.id: t.done for t in plan}["T2"] is False   # untouched

    rows = read_receipts(project / "receipts" / "receipts.jsonl")
    assert len(rows) == 1
    assert rows[0]["terminal_state"] == "COMPLETED"
    assert verify_integrity(rows[0])


def test_memories_are_injected_into_the_worker_context(project, config):
    config.max_tasks = 1
    config.auditor_enabled = False
    backend = StubBackend([fix_turn()])
    OuterLoop(project, backend, config=config).run()

    context = backend.calls[0].context
    assert context, "memories.md should be injected each iteration"
    assert "经验笔记" in context[0]
    assert "{task}" not in backend.calls[0].prompt          # template was rendered
    assert "divide" in backend.calls[0].prompt


def test_no_done_signal_is_refused_even_when_tests_pass(project, config):
    """Report §5.3: the orchestrator trusts the file, never the worker's word."""
    config.max_tasks = 1
    config.max_consecutive_failures = 3
    config.thrashing_threshold = 10
    config.auditor_enabled = False
    loop = OuterLoop(project, StubBackend([silent_turn()] * 3), config=config)

    summary = loop.run()

    assert summary.exit_code == EXIT_FAILED
    outcome = summary.outcomes[0]
    assert outcome.terminal_state == "CONSECUTIVE_FAILURES"
    assert outcome.failure_signature == "NO_DONE_SIGNAL"
    assert outcome.test_pass is False


def test_thrashing_detection_yields_stalemate(project, config):
    config.max_tasks = 1
    config.max_consecutive_failures = 10
    config.thrashing_threshold = 3
    config.auditor_enabled = False
    loop = OuterLoop(project, StubBackend([silent_turn()] * 3), config=config)

    outcome = loop.run().outcomes[0]

    assert outcome.terminal_state == "STALEMATE"
    assert outcome.iterations == 3


def test_iteration_limit(project, config):
    config.max_tasks = 1
    config.max_iterations = 2
    config.max_consecutive_failures = 99
    config.thrashing_threshold = 99
    config.auditor_enabled = False
    loop = OuterLoop(project, StubBackend([silent_turn()] * 2), config=config)

    outcome = loop.run().outcomes[0]

    assert outcome.terminal_state == "ITERATION_LIMIT"
    assert outcome.iterations == 2


def test_budget_cap_stops_the_loop(project, config):
    config.max_cost_usd = 0.005
    config.auditor_enabled = False
    loop = OuterLoop(project, StubBackend([fix_turn(cost=0.01)]), config=config)

    summary = loop.run()

    assert summary.exit_code == EXIT_LIMIT
    assert summary.total_cost_usd >= config.max_cost_usd
    assert len(summary.outcomes) == 1        # stopped before starting task 2


def test_backend_error_stops_immediately(project, config):
    config.auditor_enabled = False
    loop = OuterLoop(
        project, StubBackend([StubTurn(spawn_error="claude: command not found")]), config=config
    )

    summary = loop.run()

    assert summary.exit_code == EXIT_LIMIT
    assert summary.outcomes[0].terminal_state == "BACKEND_ERROR"
    assert summary.outcomes[0].iterations == 1


def test_kill_switch_present_before_run(project, config):
    (project / config.kill_switch_file).write_text("paused by operator", encoding="utf-8")
    summary = OuterLoop(project, StubBackend([fix_turn()]), config=config).run()

    assert summary.exit_code == EXIT_KILL_SWITCH
    assert summary.terminal_state == "KILL_SWITCH"
    assert summary.outcomes == []


def test_kill_switch_engaged_mid_run(project, config):
    config.max_consecutive_failures = 99
    config.thrashing_threshold = 99
    config.auditor_enabled = False

    def trip_switch(_outcome):
        (project / config.kill_switch_file).write_text("stop", encoding="utf-8")

    loop = OuterLoop(
        project,
        StubBackend([silent_turn()] * 4),
        config=config,
        on_iteration=trip_switch,
    )
    summary = loop.run()

    assert summary.exit_code == EXIT_KILL_SWITCH


def test_drained_plan_is_not_a_failure(project, config):
    (project / "IMPLEMENTATION_PLAN.md").write_text(
        "- [x] (T1) done\n- [x] (T2) done\n", encoding="utf-8"
    )
    summary = OuterLoop(project, StubBackend([fix_turn()]), config=config).run()

    assert summary.exit_code == EXIT_OK
    assert summary.terminal_state == "NO_TASKS"


def test_missing_plan_file_is_a_failure(project, config):
    (project / "IMPLEMENTATION_PLAN.md").unlink()
    summary = OuterLoop(project, StubBackend([fix_turn()]), config=config).run()

    assert summary.exit_code == EXIT_FAILED


def test_vcs_snapshot_is_taken_on_success(project, config):
    from rsi.vcs import NoopVCS

    config.max_tasks = 1
    config.auditor_enabled = False
    vcs = NoopVCS()
    OuterLoop(project, StubBackend([fix_turn()]), config=config, vcs=vcs).run()

    assert vcs.snapshots and vcs.snapshots[0].startswith("task T1:")


def test_a_stale_done_json_cannot_be_inherited(project, config):
    """A leftover DONE.json from a previous turn must not count as this turn's signal."""
    config.max_tasks = 1
    config.max_consecutive_failures = 1
    config.thrashing_threshold = 99
    config.auditor_enabled = False
    (project / "DONE.json").write_text(json.dumps({"test_exit_code": 0}), encoding="utf-8")

    backend = StubBackend([StubTurn(files={"notes.txt": "did nothing"}, done=None)])
    outcome = OuterLoop(project, backend, config=config).run().outcomes[0]

    assert outcome.terminal_state == "CONSECUTIVE_FAILURES"
    assert outcome.failure_signature == "NO_DONE_SIGNAL"
