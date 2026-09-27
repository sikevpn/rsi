"""S4 — golden-task regression suite, quality ratchet, autonomy ladder, CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rsi.config import LoopConfig
from rsi.gate import Gate
from rsi.inner import InnerLoop
from rsi.regression import (
    GoldenTask,
    load_golden_tasks,
    ratchet_decide,
    run_golden_suite,
)
from rsi.receipts import Receipt, append_receipt
from rsi.vcs import NoopVCS

REPO_ROOT = Path(__file__).resolve().parent.parent
SUITE = REPO_ROOT / "golden" / "tasks"
TEST_COMMAND = "python3 -m pytest -q test_calculator.py"


@pytest.fixture
def suite_config():
    cfg = LoopConfig()
    cfg.test_commands = (TEST_COMMAND,)
    return cfg


# ---------------------------------------------------------------- golden tasks


def test_shipped_suite_has_five_tasks():
    tasks = load_golden_tasks(SUITE)
    assert [t.id for t in tasks] == ["gt-001", "gt-002", "gt-003", "gt-004", "gt-005"]


def test_suite_load_is_empty_for_a_missing_directory(tmp_path):
    assert load_golden_tasks(tmp_path / "nope") == []


def test_golden_task_from_dict_defaults():
    task = GoldenTask.from_dict({"id": "x", "setup": {}, "script": []})
    assert task.expect_terminal_state == "COMPLETED"
    assert task.config_overrides == {}


def test_suite_runs_and_matches_every_expected_terminal_state(suite_config, tmp_path):
    result = run_golden_suite(load_golden_tasks(SUITE), suite_config, tmp_path)

    assert result.mismatches == (), result.mismatches
    assert result.per_task["gt-001"] == "COMPLETED"
    assert result.per_task["gt-002"] == "COMPLETED"
    assert result.per_task["gt-003"] == "STALEMATE"
    assert result.per_task["gt-004"] == "BACKEND_ERROR"
    assert result.per_task["gt-005"] == "ITERATION_LIMIT"
    assert result.metrics["runs"] == 5
    assert result.metrics["completed"] == 2


def test_suite_metrics_are_reproducible(suite_config, tmp_path):
    tasks = load_golden_tasks(SUITE)
    a = run_golden_suite(tasks, suite_config, tmp_path / "a")
    b = run_golden_suite(tasks, suite_config, tmp_path / "b")
    assert a.metrics == b.metrics


# ------------------------------------------------------------------- the ratchet


def test_ratchet_reverts_a_completion_rate_regression():
    before = {"completion_rate": 0.8, "avg_iterations": 2.0, "total_cost_usd": 1.0}
    after = {"completion_rate": 0.6, "avg_iterations": 2.0, "total_cost_usd": 1.0}
    decision = ratchet_decide(before, after)
    assert decision["decision"] == "REVERT_REGRESSED"
    assert decision["regressed"] is True
    assert decision["claim_improvement"] is False


def test_ratchet_reverts_an_iteration_regression():
    before = {"completion_rate": 0.8, "avg_iterations": 2.0, "total_cost_usd": 1.0}
    after = {"completion_rate": 0.8, "avg_iterations": 2.5, "total_cost_usd": 1.0}
    assert ratchet_decide(before, after)["decision"] == "REVERT_REGRESSED"


def test_ratchet_keeps_an_h2_qualifying_rate_improvement():
    """Report H2: completion rate +>=15% counts as a real improvement."""
    before = {"completion_rate": 0.50, "avg_iterations": 3.0, "total_cost_usd": 1.0}
    after = {"completion_rate": 0.65, "avg_iterations": 3.0, "total_cost_usd": 1.0}
    decision = ratchet_decide(before, after)
    assert decision["decision"] == "KEEP_IMPROVED"
    assert decision["claim_improvement"] is True


def test_ratchet_keeps_an_h2_qualifying_iteration_improvement():
    """Report H2: average iterations ->=10% counts as a real improvement."""
    before = {"completion_rate": 0.5, "avg_iterations": 4.0, "total_cost_usd": 1.0}
    after = {"completion_rate": 0.5, "avg_iterations": 3.5, "total_cost_usd": 1.0}
    decision = ratchet_decide(before, after)
    assert decision["decision"] == "KEEP_IMPROVED"
    assert decision["claim_improvement"] is True


def test_ratchet_does_not_claim_improvement_below_the_h2_bar():
    before = {"completion_rate": 0.50, "avg_iterations": 4.0, "total_cost_usd": 1.0}
    after = {"completion_rate": 0.60, "avg_iterations": 3.9, "total_cost_usd": 1.0}
    decision = ratchet_decide(before, after)
    assert decision["decision"] == "KEEP_NEUTRAL"
    assert decision["claim_improvement"] is False


def test_ratchet_flags_a_cost_increase():
    before = {"completion_rate": 0.5, "avg_iterations": 4.0, "total_cost_usd": 1.0}
    after = {"completion_rate": 0.5, "avg_iterations": 4.0, "total_cost_usd": 2.0}
    decision = ratchet_decide(before, after)
    assert decision["decision"] == "KEEP_NEUTRAL"
    assert any("cost rose" in r for r in decision["reasons"])


def test_regression_signal_and_acceptance_gate_are_separate(suite_config, tmp_path):
    """Anti-overfitting: re-running an unchanged config must not look like an improvement."""
    tasks = load_golden_tasks(SUITE)
    before = run_golden_suite(tasks, suite_config, tmp_path / "before").metrics
    after = run_golden_suite(tasks, suite_config, tmp_path / "after").metrics
    decision = ratchet_decide(before, after)
    assert decision["claim_improvement"] is False
    assert decision["decision"] == "KEEP_NEUTRAL"


def test_ratchet_revert_is_wired_into_the_inner_loop(project, config, suite_config, tmp_path):
    config.autonomy_level = "L3"
    config.test_commands = (TEST_COMMAND,)
    for _ in range(3):
        append_receipt(
            project / "receipts" / "receipts.jsonl",
            Receipt(task="T1", terminal_state="FAILED", failure_signature="TEST_FAIL"),
        )
    vcs = NoopVCS()
    tasks = load_golden_tasks(SUITE)
    metrics = run_golden_suite(tasks, suite_config, tmp_path).metrics
    regression = ratchet_decide(metrics, {**metrics, "completion_rate": 0.0})

    result = InnerLoop(project, config, Gate.load(project / "gate.yaml"), vcs).run(regression)

    assert result.auto_applied is True
    assert result.apply_result.reverted is True
    assert result.apply_result.applied is False
    assert vcs.reverts == 1


# ------------------------------------------------------------------------ CLI


def run_cli(*argv):
    from rsi.cli import main

    return main(list(argv))


def test_cli_doctor_reports_a_missing_backend(project, capsys):
    code = run_cli("--project", str(project), "doctor")
    out = capsys.readouterr().out
    assert code == 0
    assert "backend on PATH    : none" in out
    assert "plan               : 3 open / 3 total" in out
    assert "gate allow         : 4 pattern(s), deny 3 + 11 hardcoded" in out


def test_cli_gate_check_allows_and_blocks(project, capsys):
    assert run_cli("--project", str(project), "gate-check", "memories.md") == 0
    assert run_cli("--project", str(project), "gate-check", "gate.yaml") == 1
    assert run_cli("--project", str(project), "gate-check", "rsi/inner.py") == 1
    assert "BLOCKED" in capsys.readouterr().out


def test_cli_gate_check_enforces_the_diff_cap(project):
    assert run_cli("--project", str(project), "gate-check", "--diff-lines", "50", "memories.md") == 0
    assert run_cli("--project", str(project), "gate-check", "--diff-lines", "51", "memories.md") == 1


def test_cli_run_refuses_without_a_backend(project, capsys):
    code = run_cli("--project", str(project), "run")
    assert code == 2
    assert "no coding CLI found on PATH" in capsys.readouterr().err


def test_cli_receipts_on_an_empty_ledger(project, capsys):
    assert run_cli("--project", str(project), "receipts") == 0
    assert "0 receipt(s)" in capsys.readouterr().out


def test_cli_meta_reports_insufficient_evidence(project, capsys):
    assert run_cli("--project", str(project), "meta") == 0
    assert "INSUFFICIENT_EVIDENCE" in capsys.readouterr().out


def test_cli_meta_emits_a_proposal_after_enough_evidence(project, capsys):
    for _ in range(5):
        append_receipt(
            project / "receipts" / "receipts.jsonl",
            Receipt(task="T1", terminal_state="FAILED", failure_signature="NO_DONE_SIGNAL"),
        )
    assert run_cli("--project", str(project), "meta") == 0
    out = capsys.readouterr().out
    assert "EXECUTION_CHOICE" in out
    assert "memories.md" in out
    assert (project / "proposals.md").exists()


def test_cli_regress_runs_the_shipped_suite(project, capsys):
    code = run_cli("--project", str(project), "regress", "--suite", str(SUITE))
    out = capsys.readouterr().out
    assert code == 0, out
    assert "MISMATCH" not in out
    assert "gt-001: COMPLETED" in out


def test_cli_regress_fails_when_the_suite_is_empty(project, tmp_path, capsys):
    assert run_cli("--project", str(project), "regress", "--suite", str(tmp_path)) == 2


def test_cli_version(capsys):
    with pytest.raises(SystemExit) as exc:
        run_cli("--version")
    assert exc.value.code == 0
    assert "rsi" in capsys.readouterr().out
