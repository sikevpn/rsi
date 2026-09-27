"""Run receipts — the immutable evidence record of one outer-loop run.

Copies the loopy receipt schema referenced in report §3.4 / §5.3: an SHA-256-pinned,
terminal-state-enumerated record that the inner loop debriefs against.  Pinning matters
because the report's anti-overfitting rule ("优化信号 ≠ 验收门") requires that the
evidence used to justify a self-change cannot be silently rewritten afterwards.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

__all__ = [
    "TERMINAL_STATES",
    "ATTRIBUTIONS",
    "Receipt",
    "canonical_json",
    "compute_sha256",
    "append_receipt",
    "read_receipts",
    "read_recent",
    "verify_integrity",
]

#: Closed enumeration — a receipt must name why the loop stopped (report §3.3).
TERMINAL_STATES: tuple[str, ...] = (
    "COMPLETED",
    "FAILED",
    "NO_TASKS",
    "ITERATION_LIMIT",
    "CONSECUTIVE_FAILURES",
    "STALEMATE",
    "BUDGET_EXHAUSTED",
    "BACKEND_ERROR",
    "AUDIT_REJECTED",
    "GATE_BLOCKED",
    "KILL_SWITCH",
)

#: loopy's four-cause debrief taxonomy (report §6 stage 3, step 2).
ATTRIBUTIONS: tuple[str, ...] = (
    "LOOP_DESIGN",
    "EXECUTION_CHOICE",
    "ENVIRONMENT_TOOL",
    "UNREALISTIC_GOAL",
    "INSUFFICIENT_EVIDENCE",
)

_SCHEMA_VERSION = 1


def canonical_json(obj: Any) -> str:
    """Deterministic JSON so hashes are reproducible across runs and machines."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_sha256(payload: dict[str, Any]) -> str:
    body = {k: v for k, v in payload.items() if k != "sha256"}
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


@dataclass
class Receipt:
    """One outer-loop run, frozen into evidence."""

    task: str
    terminal_state: str
    mode: str = "build"
    iterations: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    test_pass: bool = False
    verdict: str = "unknown"
    attribution: str | None = None
    failure_signature: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    notes: str = ""
    next_step: str = ""
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    schema_version: int = _SCHEMA_VERSION
    sha256: str = ""

    def __post_init__(self) -> None:
        if self.terminal_state not in TERMINAL_STATES:
            raise ValueError(
                f"terminal_state {self.terminal_state!r} not in {TERMINAL_STATES}"
            )
        if self.attribution is not None and self.attribution not in ATTRIBUTIONS:
            raise ValueError(f"attribution {self.attribution!r} not in {ATTRIBUTIONS}")
        if not self.sha256:
            self.sha256 = compute_sha256(self.payload())

    def payload(self) -> dict[str, Any]:
        data = asdict(self)
        data["evidence"] = json.loads(json.dumps(self.evidence, default=str))
        return data

    def to_json(self) -> str:
        return json.dumps(self.payload(), sort_keys=True, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Receipt":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


def append_receipt(path: str | Path, receipt: Receipt) -> Receipt:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(receipt.to_json() + "\n")
    return receipt


def read_receipts(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        out.append(json.loads(line))
    return out


def read_recent(path: str | Path, count: int) -> list[dict[str, Any]]:
    if count <= 0:
        return []
    return read_receipts(path)[-count:]


def verify_integrity(record: dict[str, Any]) -> bool:
    """Recompute the pin.  False means the receipt was edited after the fact."""
    return compute_sha256(record) == record.get("sha256")


def summarize(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate metrics used by the regression ratchet."""
    rows = list(records)
    total = len(rows)
    completed = sum(1 for r in rows if r.get("terminal_state") == "COMPLETED")
    return {
        "runs": total,
        "completed": completed,
        "completion_rate": (completed / total) if total else 0.0,
        "avg_iterations": (sum(r.get("iterations", 0) for r in rows) / total) if total else 0.0,
        "total_tokens": sum(r.get("tokens", 0) for r in rows),
        "avg_tokens": (sum(r.get("tokens", 0) for r in rows) / total) if total else 0.0,
        "total_cost_usd": round(sum(float(r.get("cost_usd", 0.0)) for r in rows), 6),
    }
