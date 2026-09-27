"""Inner loop — the recursive self-improvement layer (report §5.2 ③, §6 stages 3–4).

This is the layer the report says none of the 11 surveyed projects actually ships
(§1.2, §8.1 conclusion 1).  The chain is:

    recent receipts -> debrief (four-cause attribution) -> one minimal change
    -> gate check -> snapshot -> regression -> keep or revert

Two disciplines are enforced in code, not in prose:

* **Anti-overfitting** — fewer than ``min_samples_for_pattern`` receipts yields
  ``INSUFFICIENT_EVIDENCE`` and *no* proposal at all ("单跑=一个数据点不构成模式");
* **Minimal change** — exactly one edit, and its diff is capped by the gate (report H5).
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from .config import LoopConfig
from .gate import Gate, GateVerdict
from .receipts import ATTRIBUTIONS, Receipt, read_recent
from .vcs import NoopVCS, VCS

__all__ = [
    "NO_FAILURES",
    "Proposal",
    "DebriefResult",
    "ApplyResult",
    "InnerResult",
    "InnerLoop",
    "debrief",
    "propose_minimal_change",
    "can_auto_apply",
    "LOOP_DESIGN_SIGNATURES",
    "EXECUTION_SIGNATURES",
    "ENVIRONMENT_SIGNATURES",
]

#: A fifth bucket beyond loopy's four causes: nothing went wrong, so there is nothing to
#: attribute.  Keeping it explicit stops the loop inventing a cause to justify an edit.
NO_FAILURES = "NO_FAILURES"

LOOP_DESIGN_SIGNATURES = frozenset({"ITERATION_LIMIT", "STALEMATE"})
EXECUTION_SIGNATURES = frozenset(
    {"TEST_FAIL", "CLAIM_MISMATCH", "AUDIT_FAIL", "NO_DONE_SIGNAL", "FAILED"}
)
ENVIRONMENT_SIGNATURES = frozenset({"BACKEND_ERROR"})

_LESSONS = {
    "NO_DONE_SIGNAL": (
        "完成信号只认根目录 DONE.json。stdout 不会被解析；没写 DONE.json 的轮次一律记失败。"
    ),
    "TEST_FAIL": (
        "改完必须真跑验证命令并把真实退出码写进 DONE.json 的 test_exit_code，"
        "编排器会独立复跑对账。"
    ),
    "CLAIM_MISMATCH": (
        "DONE.json 的 test_exit_code 必须是刚跑出来的真实值；与编排器复跑结果不一致会被判作弊。"
    ),
    "AUDIT_FAIL": (
        "审计者会检查测试是否净减少、断言是否被改弱。不要靠删测试或加 skip 让套件变绿。"
    ),
}


@dataclass
class DebriefResult:
    attribution: str
    sample_size: int
    signature_counts: dict[str, int]
    sufficient_evidence: bool
    reason: str

    def __post_init__(self) -> None:
        valid = set(ATTRIBUTIONS) | {NO_FAILURES}
        if self.attribution not in valid:
            raise ValueError(f"attribution {self.attribution!r} not in {sorted(valid)}")


def _signature(record: dict[str, Any]) -> str:
    return str(record.get("failure_signature") or record.get("terminal_state") or "")


def debrief(records: Sequence[dict[str, Any]], min_samples: int = 3) -> DebriefResult:
    """Classify a window of receipts into exactly one cause — or refuse to classify."""
    rows = list(records)
    counts: dict[str, int] = dict(Counter(_signature(r) for r in rows))

    if len(rows) < min_samples:
        return DebriefResult(
            attribution="INSUFFICIENT_EVIDENCE",
            sample_size=len(rows),
            signature_counts=counts,
            sufficient_evidence=False,
            reason=(
                f"{len(rows)} receipt(s) < min_samples_for_pattern={min_samples}; "
                "one run is a data point, not a pattern"
            ),
        )

    failures = [r for r in rows if r.get("terminal_state") != "COMPLETED"]
    if not failures:
        return DebriefResult(
            attribution=NO_FAILURES,
            sample_size=len(rows),
            signature_counts=counts,
            sufficient_evidence=True,
            reason="every receipt in the window completed; nothing to attribute",
        )

    sigs = [_signature(r) for r in failures]
    env = sum(1 for s in sigs if s in ENVIRONMENT_SIGNATURES)
    design = sum(1 for s in sigs if s in LOOP_DESIGN_SIGNATURES)
    execution = sum(1 for s in sigs if s in EXECUTION_SIGNATURES)

    if env:
        attribution, reason = "ENVIRONMENT_TOOL", f"{env} backend/environment failure(s)"
    elif design >= execution and design > 0:
        attribution, reason = "LOOP_DESIGN", f"{design} limit/stalemate failure(s)"
    elif execution > 0:
        attribution, reason = "EXECUTION_CHOICE", f"{execution} execution failure(s)"
    else:
        attribution, reason = "UNREALISTIC_GOAL", "failures match no known signature"

    return DebriefResult(
        attribution=attribution,
        sample_size=len(rows),
        signature_counts=counts,
        sufficient_evidence=True,
        reason=reason,
    )


@dataclass
class Proposal:
    attribution: str
    path: str
    action: str                     # "append"
    content: str
    rationale: str
    evidence_receipts: tuple[str, ...] = ()
    risk: str = "low"               # "low" | "high"
    ts: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    @property
    def diff_lines(self) -> int:
        return len([line for line in self.content.splitlines() if line.strip()])

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["evidence_receipts"] = list(self.evidence_receipts)
        data["diff_lines"] = self.diff_lines
        return data


def propose_minimal_change(
    result: DebriefResult,
    records: Sequence[dict[str, Any]],
    config: LoopConfig | None = None,
) -> Proposal | None:
    """Return one minimal edit, or None when the evidence does not justify one."""
    if not result.sufficient_evidence or result.attribution in {NO_FAILURES}:
        return None
    if result.attribution in {"ENVIRONMENT_TOOL", "UNREALISTIC_GOAL"}:
        # Report §6 stage 3: environment failures and unrealistic goals are escalated to a
        # human, never "fixed" by editing our own prompt.
        return None

    rows = list(records)
    evidence = tuple(str(r.get("sha256", ""))[:12] for r in rows if r.get("sha256"))[:5]
    dominant = max(
        result.signature_counts.items(), key=lambda kv: (kv[1], kv[0] in EXECUTION_SIGNATURES)
    )[0]

    if result.attribution == "EXECUTION_CHOICE":
        lesson = _LESSONS.get(dominant, f"最近 {result.sample_size} 轮的主导失败签名是 {dominant}。")
        return Proposal(
            attribution=result.attribution,
            path="memories.md",
            action="append",
            content=f"- {lesson}",
            rationale=(
                f"{result.sample_size} 条 receipt 中主导失败签名为 {dominant!r}"
                f"（{result.signature_counts}）；{result.reason}"
            ),
            evidence_receipts=evidence,
            risk="low",
        )

    # LOOP_DESIGN -> one parameter-level nudge in config/, which the gate allow-lists.
    cfg = config or LoopConfig()
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return Proposal(
        attribution=result.attribution,
        path="config/loop.yaml",
        action="append",
        content=f"# meta note ({result.attribution}, {stamp}): 主导签名 {dominant!r}",
        rationale=(
            f"{result.sample_size} 条 receipt 中 {result.reason}；"
            f"当前 max_iterations={cfg.max_iterations}，建议人工复核后调整"
        ),
        evidence_receipts=evidence,
        risk="high",
    )


def can_auto_apply(proposal: Proposal, autonomy_level: str) -> bool:
    """Report §3.3 autonomy ladder: L1 never auto-applies."""
    if autonomy_level == "L1":
        return False
    if autonomy_level == "L2":
        return proposal.risk == "low"
    return autonomy_level == "L3"


@dataclass
class ApplyResult:
    applied: bool
    reason: str
    gate_verdict: GateVerdict | None = None
    snapshot_taken: bool = False
    reverted: bool = False


@dataclass
class InnerResult:
    debrief: DebriefResult
    proposal: Proposal | None
    autonomy_level: str
    auto_applied: bool
    apply_result: ApplyResult
    proposal_recorded: bool
    regression: dict[str, Any] | None = None


class InnerLoop:
    def __init__(
        self,
        project_root: str | Path,
        config: LoopConfig | None = None,
        gate: Gate | None = None,
        vcs: VCS | None = None,
    ) -> None:
        self.root = Path(project_root)
        self.config = config or LoopConfig()
        self.gate = gate or Gate.load(self.root / self.config.gate_file)
        self.vcs = vcs or NoopVCS()

    # ------------------------------------------------------------- triggers

    def receipt_count(self) -> int:
        path = self.root / self.config.receipts_file
        if not path.exists():
            return 0
        return len([ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()])

    def should_trigger(self) -> bool:
        """Every ``inner_loop_every`` completed runs (report §5.4 item 4)."""
        every = max(1, self.config.inner_loop_every)
        count = self.receipt_count()
        return count > 0 and count % every == 0

    def recent(self) -> list[dict[str, Any]]:
        return read_recent(
            self.root / self.config.receipts_file, max(1, self.config.inner_loop_every)
        )

    # -------------------------------------------------------------- writing

    def record_proposal(self, proposal: Proposal) -> bool:
        path = self.root / self.config.proposals_file
        path.parent.mkdir(parents=True, exist_ok=True)
        header = "" if path.exists() else "# 自改提案（L1 report-only，人批准后才应用）\n\n"
        block = (
            f"## {proposal.ts} — {proposal.attribution} → `{proposal.path}` ({proposal.risk} risk)\n\n"
            f"- **理由**：{proposal.rationale}\n"
            f"- **动作**：{proposal.action}，diff {proposal.diff_lines} 行\n"
            f"- **证据 receipt**：{', '.join(proposal.evidence_receipts) or '(无)'}\n\n"
            "```json\n" + json.dumps(proposal.to_dict(), ensure_ascii=False, indent=2) + "\n```\n\n"
        )
        with path.open("a", encoding="utf-8") as fh:
            fh.write(header + block)
        return True

    # -------------------------------------------------------------- applying

    def apply(self, proposal: Proposal, regression: dict[str, Any] | None = None) -> ApplyResult:
        verdict = self.gate.check([proposal.path], diff_lines=proposal.diff_lines)
        if not verdict.allowed:
            return ApplyResult(applied=False, reason=verdict.explain(), gate_verdict=verdict)

        target = self.root / proposal.path
        if proposal.action != "append":
            return ApplyResult(
                applied=False,
                reason=f"unsupported action {proposal.action!r} (MVP supports 'append' only)",
                gate_verdict=verdict,
            )

        snapshotted = self.vcs.snapshot(f"pre-self-modification snapshot ({proposal.path})")
        target.parent.mkdir(parents=True, exist_ok=True)
        existing = target.read_text(encoding="utf-8") if target.exists() else ""
        sep = "" if existing.endswith("\n") or not existing else "\n"
        target.write_text(existing + sep + proposal.content + "\n", encoding="utf-8")

        reverted = False
        if regression is not None and regression.get("decision") == "REVERT_REGRESSED":
            self.vcs.revert_last()
            reverted = True

        return ApplyResult(
            applied=not reverted,
            reason=(
                "reverted: regression suite got worse"
                if reverted
                else f"applied to {proposal.path} (gate: {verdict.explain()})"
            ),
            gate_verdict=verdict,
            snapshot_taken=snapshotted,
            reverted=reverted,
        )

    # ------------------------------------------------------------------ run

    def run(self, regression: dict[str, Any] | None = None) -> InnerResult:
        records = self.recent()
        result = debrief(records, self.config.min_samples_for_pattern)
        proposal = propose_minimal_change(result, records, self.config)

        if proposal is None:
            return InnerResult(
                debrief=result,
                proposal=None,
                autonomy_level=self.config.autonomy_level,
                auto_applied=False,
                apply_result=ApplyResult(applied=False, reason=result.reason),
                proposal_recorded=False,
            )

        auto = can_auto_apply(proposal, self.config.autonomy_level)
        if not auto:
            # L1 report-only: propose, never touch the tree.
            self.record_proposal(proposal)
            return InnerResult(
                debrief=result,
                proposal=proposal,
                autonomy_level=self.config.autonomy_level,
                auto_applied=False,
                apply_result=ApplyResult(applied=False, reason="L1 report-only: proposal not applied"),
                proposal_recorded=True,
            )

        apply_result = self.apply(proposal, regression)
        return InnerResult(
            debrief=result,
            proposal=proposal,
            autonomy_level=self.config.autonomy_level,
            auto_applied=True,
            apply_result=apply_result,
            proposal_recorded=self.record_proposal(proposal),
            regression=regression,
        )


__all__ = tuple(__all__) + ("Receipt",)
