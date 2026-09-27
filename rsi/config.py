"""Loop configuration — the tunable surface the inner loop is allowed to modify.

Kept in ``config/loop.yaml`` because the report puts parameter-level config inside the
self-modification allow-list (§4: ``config/*.yaml``（参数级）).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import miniyaml

__all__ = ["LoopConfig", "AUTONOMY_LEVELS"]

#: Report §3.3 "自治阶梯": L1 report-only -> L2 cautious -> L3 unattended.
AUTONOMY_LEVELS: tuple[str, ...] = ("L1", "L2", "L3")


@dataclass
class LoopConfig:
    # guardrails (report §3.3 防死循环 / 成本控制)
    max_iterations: int = 50
    max_consecutive_failures: int = 3
    thrashing_threshold: int = 3
    max_cost_usd: float = 10.0
    max_tasks: int = 0                       # 0 = drain the whole plan
    timeout_s: float = 900.0

    # backpressure (report §3.3)
    test_commands: tuple[str, ...] = ()

    # verification layer (report §6 stage 2)
    auditor_enabled: bool = True
    count_command: str = ""                  # collect-only, feeds the net-decrease guard
    test_globs: tuple[str, ...] = ("test_*.py", "tests/**/*.py")

    # inner loop (report §6 stage 3)
    inner_loop_every: int = 5
    min_samples_for_pattern: int = 3         # anti-overfitting: one run is not a pattern
    max_self_diff_lines: int = 50            # H5

    # memory (report §3.4)
    memory_max_chars: int = 4000

    # safety (report §4)
    autonomy_level: str = "L1"
    kill_switch_file: str = "LOOP_PAUSED"

    # paths
    plan_file: str = "IMPLEMENTATION_PLAN.md"
    memories_file: str = "memories.md"
    receipts_file: str = "receipts/receipts.jsonl"
    proposals_file: str = "proposals.md"
    gate_file: str = "gate.yaml"
    prompts_dir: str = "prompts"
    done_file: str = "DONE.json"
    audit_file: str = "AUDIT.json"

    source: str = "<defaults>"
    raw: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.autonomy_level not in AUTONOMY_LEVELS:
            raise ValueError(
                f"autonomy_level {self.autonomy_level!r} not in {AUTONOMY_LEVELS}"
            )
        if self.max_iterations < 1:
            raise ValueError("max_iterations must be >= 1")
        if self.max_consecutive_failures < 1:
            raise ValueError("max_consecutive_failures must be >= 1")

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None, source: str = "<dict>") -> "LoopConfig":
        data = data or {}
        if not isinstance(data, dict):
            raise ValueError(f"config document must be a mapping, got {type(data).__name__}")
        known = set(cls.__dataclass_fields__) - {"source", "raw"}  # type: ignore[attr-defined]
        kwargs: dict[str, Any] = {}
        for key, value in data.items():
            if key not in known:
                continue
            if key == "test_commands":
                if value is None:
                    kwargs[key] = ()
                elif isinstance(value, str):
                    kwargs[key] = (value,)
                else:
                    kwargs[key] = tuple(str(v) for v in value)
            elif key == "test_globs":
                if value is None:
                    kwargs[key] = ()
                elif isinstance(value, str):
                    kwargs[key] = (value,)
                else:
                    kwargs[key] = tuple(str(v) for v in value)
            else:
                kwargs[key] = value
        return cls(source=source, raw=dict(data), **kwargs)

    @classmethod
    def load(cls, path: str | Path, engine: str = "mini") -> "LoopConfig":
        p = Path(path)
        if not p.exists():
            return cls(source=f"<missing:{p}>")
        return cls.from_dict(miniyaml.load_file(p, engine=engine), source=str(p))

    def prompt_path(self, mode: str) -> str:
        return f"{self.prompts_dir}/PROMPT_{mode}.md"
