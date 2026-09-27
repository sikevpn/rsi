"""RSI (Recursive Self-Improvement) coding agent — thin orchestration glue.

Implements the two-layer architecture from ``RSI代理开发战略报告.md`` §5.2:

    ⑤ scheduler  ->  ① outer loop  ->  ② verification  ->  ③ inner loop  ->  ④ memory/state

Design constraints honoured here:
  * zero third-party runtime dependencies (report §5.1 "自研胶水层极薄");
  * completion signals are read from files, never parsed out of free-form stdout
    (report §5.3, ralph-orchestrator anti-confabulation);
  * self-modification is bounded by a machine-enforced gate, not by prompt discipline
    (report §4 assumption 4).
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
