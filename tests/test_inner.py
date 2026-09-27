"""S3 — inner loop: debrief, minimal change, autonomy ladder, gate, ratchet revert."""

from __future__ import annotations

import json

import pytest

from rsi.config import LoopConfig
from rsi.gate import Gate
from rsi.inner import (
    NO_FAILURES,
    InnerLoop,
    Proposal,
    can_auto_apply,
    debrief,
    propose_minimal_change,
)
from rsi.receipts import Receipt, append_receipt, read_receipts
from rsi.vcs import NoopVCS


def rec(state, sig="", sha="a" * 64):
    r = Receipt(task="T1: x", terminal_state=state, failure_signature=sig, iterations=1)
    payload = r.payload()
    payload["sha256"] = sha
    return payload


# --------------------------------------------------------------------- debrief


def test_insufficient_evidence_blocks_any_conclusion():
    """Report anti-overfitting rule: one run is a data point, not a pattern."""
    result = debrief([rec("FAILED", "TEST_FAIL")] * 2, min_samples=3)
    assert result.attribution == "INSUFFICIENT_EVIDENCE"
    assert result.sufficient_evidence is False
    assert propose_minimal_change(result, [rec("FAILED", "TEST_FAIL")] * 2) is None


def test_no_failures_yields_no_proposal():
    rows = [rec("COMPLETED")] * 4
    result = debrief(rows, min_samples=3)
    assert result.attribution == NO_FAILURES
    assert result.sufficient_evidence is True
    assert propose_minimal_change(result, rows) is None


def test_environment_failure_dominates_attribution():
    rows = [rec("BACKEND_ERROR", "BACKEND_ERROR")] + [rec("FAILED", "TEST_FAIL")] * 3
    assert debrief(rows, 3).attribution == "ENVIRONMENT_TOOL"


def test_loop_design_attribution():
    rows = [rec("STALEMATE", "STALEMATE")] * 2 + [rec("ITERATION_LIMIT", "ITERATION_LIMIT")]
    assert debrief(rows, 3).attribution == "LOOP_DESIGN"


def test_execution_choice_attribution():
    rows = [rec("FAILED", "TEST_FAIL")] * 2 + [rec("FAILED", "NO_DONE_SIGNAL")]
    assert debrief(rows, 3).attribution == "EXECUTION_CHOICE"


def test_unknown_signatures_fall_back_to_unrealistic_goal():
    rows = [rec("FAILED", "SOMETHING_ELSE")] * 3
    assert debrief(rows, 3).attribution == "UNREALISTIC_GOAL"


@pytest.mark.parametrize("attribution", ["ENVIRONMENT_TOOL", "UNREALISTIC_GOAL"])
def test_environment_and_goal_problems_are_escalated_not_self_fixed(attribution):
    rows = [rec("FAILED", "BACKEND_ERROR" if attribution == "ENVIRONMENT_TOOL" else "X")] * 3
    result = debrief(rows, 3)
    assert result.attribution == attribution
    assert propose_minimal_change(result, rows) is None


# -------------------------------------------------------------------- proposals


def test_execution_choice_proposes_a_single_memory_append():
    rows = [rec("FAILED", "NO_DONE_SIGNAL", sha=f"{i:064d}") for i in range(3)]
    result = debrief(rows, 3)
    proposal = propose_minimal_change(result, rows)

    assert proposal is not None
    assert proposal.path == "memories.md"
    assert proposal.action == "append"
    assert proposal.risk == "low"
    assert proposal.diff_lines == 1                 # minimal single change
    assert "DONE.json" in proposal.content
    assert len(proposal.evidence_receipts) == 3
    assert proposal.rationale


def test_loop_design_proposal_is_marked_high_risk():
    rows = [rec("STALEMATE", "STALEMATE")] * 3
    proposal = propose_minimal_change(debrief(rows, 3), rows)
    assert proposal is not None
    assert proposal.path == "config/loop.yaml"
    assert proposal.risk == "high"


@pytest.mark.parametrize(
    "level,risk,expected",
    [("L1", "low", False), ("L1", "high", False), ("L2", "low", True),
     ("L2", "high", False), ("L3", "high", True)],
)
def test_autonomy_ladder(level, risk, expected):
    proposal = Proposal(attribution="X", path="memories.md", action="append",
                        content="- x", rationale="r", risk=risk)
    assert can_auto_apply(proposal, level) is expected


# ----------------------------------------------------------------- inner loop run


def seed(project, states):
    path = project / "receipts" / "receipts.jsonl"
    for state, sig in states:
        append_receipt(path, Receipt(task="T1: x", terminal_state=state,
                                     failure_signature=sig, iterations=1))


def test_l1_writes_a_proposal_and_touches_nothing(project, config):
    config.autonomy_level = "L1"
    seed(project, [("FAILED", "NO_DONE_SIGNAL")] * 3)
    before = (project / "memories.md").read_text(encoding="utf-8")

    result = InnerLoop(project, config, Gate.load(project / "gate.yaml"), NoopVCS()).run()

    assert result.proposal is not None
    assert result.proposal_recorded is True
    assert result.auto_applied is False
    assert (project / "memories.md").read_text(encoding="utf-8") == before   # untouched
    assert "NO_DONE_SIGNAL" in (project / "proposals.md").read_text(encoding="utf-8")
    json.loads(
        (project / "proposals.md").read_text(encoding="utf-8").split("```json")[1].split("```")[0]
    )


def test_l2_auto_applies_a_low_risk_memory_append(project, config):
    config.autonomy_level = "L2"
    seed(project, [("FAILED", "TEST_FAIL")] * 3)
    before = (project / "memories.md").read_text(encoding="utf-8")

    result = InnerLoop(project, config, Gate.load(project / "gate.yaml"), NoopVCS()).run()

    assert result.auto_applied is True
    assert result.apply_result.applied is True
    after = (project / "memories.md").read_text(encoding="utf-8")
    assert after != before and after.startswith(before.rstrip("\n"))


def test_l2_refuses_a_high_risk_change(project, config):
    config.autonomy_level = "L2"
    seed(project, [("STALEMATE", "STALEMATE")] * 3)

    result = InnerLoop(project, config, Gate.load(project / "gate.yaml"), NoopVCS()).run()

    assert result.proposal.risk == "high"
    assert result.auto_applied is False
    assert "report-only" in result.apply_result.reason


def test_gate_blocks_a_proposal_targeting_a_denied_path(project, config):
    config.autonomy_level = "L3"
    gate = Gate.load(project / "gate.yaml")
    loop = InnerLoop(project, config, gate, NoopVCS())
    hostile = Proposal(attribution="EXECUTION_CHOICE", path="IMPLEMENTATION_PLAN.md",
                       action="append", content="- [x] (T1) forged", rationale="r")

    result = loop.apply(hostile)

    assert result.applied is False
    assert "deny pattern" in result.reason


def test_h5_caps_the_self_modification_diff(project, config):
    config.autonomy_level = "L3"
    loop = InnerLoop(project, config, Gate.load(project / "gate.yaml"), NoopVCS())
    bloated = Proposal(attribution="EXECUTION_CHOICE", path="memories.md", action="append",
                       content="\n".join(f"- line {i}" for i in range(51)), rationale="r")

    assert bloated.diff_lines == 51
    result = loop.apply(bloated)
    assert result.applied is False
    assert "minimal-change principle" in result.reason


def test_regression_reverts_the_self_modification(project, config):
    config.autonomy_level = "L3"
    vcs = NoopVCS()
    loop = InnerLoop(project, config, Gate.load(project / "gate.yaml"), vcs)
    proposal = Proposal(attribution="EXECUTION_CHOICE", path="memories.md", action="append",
                        content="- learned", rationale="r")

    result = loop.apply(proposal, regression={"decision": "REVERT_REGRESSED"})

    assert result.applied is False
    assert result.reverted is True
    assert vcs.reverts == 1
    assert vcs.snapshots                        # snapshot taken before the edit


def test_snapshot_is_taken_before_applying(project, config):
    config.autonomy_level = "L3"
    vcs = NoopVCS()
    loop = InnerLoop(project, config, Gate.load(project / "gate.yaml"), vcs)
    proposal = Proposal(attribution="EXECUTION_CHOICE", path="memories.md", action="append",
                        content="- learned", rationale="r")

    assert loop.apply(proposal).applied is True
    assert vcs.snapshots == ["pre-self-modification snapshot (memories.md)"]


def test_unsupported_action_is_refused(project, config):
    config.autonomy_level = "L3"
    loop = InnerLoop(project, config, Gate.load(project / "gate.yaml"), NoopVCS())
    result = loop.apply(Proposal(attribution="X", path="memories.md", action="rewrite",
                                 content="x", rationale="r"))
    assert result.applied is False
    assert "unsupported action" in result.reason


# -------------------------------------------------------------------- triggering


def test_should_trigger_only_on_the_inner_loop_cadence(project, config):
    config.inner_loop_every = 5
    loop = InnerLoop(project, config, Gate.load(project / "gate.yaml"))
    assert loop.should_trigger() is False

    seed(project, [("COMPLETED", "")] * 4)
    assert loop.should_trigger() is False

    seed(project, [("COMPLETED", "")])
    assert loop.receipt_count() == 5
    assert loop.should_trigger() is True


def test_run_without_evidence_proposes_nothing(project, config):
    config.autonomy_level = "L3"
    result = InnerLoop(project, config, Gate.load(project / "gate.yaml")).run()
    assert result.proposal is None
    assert result.debrief.attribution == "INSUFFICIENT_EVIDENCE"
    assert not (project / "proposals.md").exists()


def test_applied_memory_becomes_visible_to_the_next_outer_run(project, config):
    """The loop must actually close: what the inner loop writes, the outer loop reads."""
    from rsi.backend import StubBackend, StubTurn
    from rsi.blackboard import load_memories
    from rsi.outer import OuterLoop

    config.autonomy_level = "L2"
    config.max_tasks = 1
    config.auditor_enabled = False
    seed(project, [("FAILED", "NO_DONE_SIGNAL")] * 3)
    InnerLoop(project, config, Gate.load(project / "gate.yaml"), NoopVCS()).run()

    injected = load_memories(project / "memories.md", config.memory_max_chars)
    assert "DONE.json" in injected

    backend = StubBackend([StubTurn(done=None)])
    OuterLoop(project, backend, config=config).run()
    assert "DONE.json" in backend.calls[0].context[0]


def test_receipts_written_by_the_loop_are_all_pinned(project, config):
    from rsi.backend import StubBackend, StubTurn
    from rsi.outer import OuterLoop

    config.max_tasks = 1
    config.max_consecutive_failures = 1
    config.auditor_enabled = False
    OuterLoop(project, StubBackend([StubTurn(done=None)]), config=config).run()

    rows = read_receipts(project / "receipts" / "receipts.jsonl")
    assert rows and all(verify(r) for r in rows)


def verify(row):
    from rsi.receipts import verify_integrity

    return verify_integrity(row)
