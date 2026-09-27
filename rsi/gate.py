"""Machine-enforced self-modification gate (report §4 assumption 4).

The report is explicit that the boundary must be *mechanically* enforced, not left to
prompt discipline: "gate.yaml 黑名单在文件系统层硬编码拦截，不靠 prompt 自觉".  Two
layers therefore apply:

1. ``HARD_DENY`` — hardcoded in the orchestrator itself, cannot be widened by editing
   ``gate.yaml`` (the gate file protects itself).
2. ``gate.yaml`` — project-level allow/deny lists plus per-change size caps.

A path is allowed only when it matches an allow pattern **and** matches no deny pattern.
"""

from __future__ import annotations

import fnmatch  # noqa: F401  (kept for pattern familiarity; matcher below is stricter)
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Sequence

from . import miniyaml

__all__ = ["Gate", "GateVerdict", "HARD_DENY", "DEFAULT_ALLOW", "match", "load_gate"]

#: Hardcoded blacklist.  Editing gate.yaml cannot remove these.
HARD_DENY: tuple[str, ...] = (
    "rsi/**",            # orchestrator source (report: "编排器自身源码")
    "gate.yaml",         # the gate must not be able to widen itself
    "**/gate.yaml",
    ".git/**",
    ".env",
    ".env.*",
    "**/.env",
    "**/.env.*",
    "secrets/**",
    "auth/**",
    "migrations/**",
)

#: Default allow-list, mirrors report §4 table row "可自改目录（白名单）".
DEFAULT_ALLOW: tuple[str, ...] = (
    "prompts/*.md",
    "memories.md",
    "config/*.yaml",
    "skills/*.md",
)


@dataclass(frozen=True)
class GateVerdict:
    """Outcome of a gate check.  ``allowed`` is False if ``violations`` is non-empty."""

    allowed: bool
    violations: tuple[str, ...] = ()
    matched_allow: tuple[str, ...] = ()
    files_checked: int = 0

    def explain(self) -> str:
        if self.allowed:
            return f"allowed ({self.files_checked} file(s))"
        return "BLOCKED: " + "; ".join(self.violations)


def _compile(pattern: str) -> re.Pattern[str]:
    """Glob -> regex with precise semantics: ``**`` spans '/', ``*`` does not."""
    out: list[str] = []
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "*":
            if pattern[i : i + 2] == "**":
                out.append(".*")
                i += 2
                if i < len(pattern) and pattern[i] == "/":
                    i += 1  # '**/' also matches zero directories
                continue
            out.append("[^/]*")
            i += 1
        elif ch == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(ch))
            i += 1
    return re.compile("^" + "".join(out) + "$")


_CACHE: dict[str, re.Pattern[str]] = {}


def _regex(pattern: str) -> re.Pattern[str]:
    if pattern not in _CACHE:
        _CACHE[pattern] = _compile(pattern)
    return _CACHE[pattern]


def match(pattern: str, path: str) -> bool:
    return _regex(pattern).match(path) is not None


def normalize(path: str | Path) -> str:
    """Return a repo-relative POSIX path, or raise on absolute/escaping paths."""
    text = str(path).replace("\\", "/").strip()
    if not text:
        raise ValueError("empty path")
    if text.startswith("/") or (len(text) > 1 and text[1] == ":"):
        raise ValueError(f"absolute path is not allowed: {path!r}")
    parts: list[str] = []
    for part in PurePosixPath(text).parts:
        if part == ".":
            continue
        if part == "..":
            raise ValueError(f"path escapes the project root: {path!r}")
        parts.append(part)
    if not parts:
        raise ValueError(f"path resolves to the project root: {path!r}")
    return "/".join(parts)


@dataclass
class Gate:
    """Loaded gate policy."""

    allow: tuple[str, ...] = DEFAULT_ALLOW
    deny: tuple[str, ...] = ()
    hard_deny: tuple[str, ...] = HARD_DENY
    max_files_per_change: int = 10
    max_diff_lines: int = 50
    source: str = "<defaults>"
    raw: dict[str, Any] = field(default_factory=dict)

    # ---------------------------------------------------------------- loading

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None, source: str = "<dict>") -> "Gate":
        data = data or {}
        if not isinstance(data, dict):
            raise ValueError(f"gate document must be a mapping, got {type(data).__name__}")

        def _strings(key: str, fallback: Sequence[str]) -> tuple[str, ...]:
            value = data.get(key, list(fallback))
            if value is None:
                return ()
            if isinstance(value, str):
                return (value,)
            if not isinstance(value, list):
                raise ValueError(f"gate key {key!r} must be a list of patterns")
            return tuple(str(v) for v in value)

        def _int(key: str, fallback: int) -> int:
            value = data.get(key, fallback)
            if value is None:
                return fallback
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"gate key {key!r} must be an integer")
            if value <= 0:
                raise ValueError(f"gate key {key!r} must be positive")
            return int(value)

        return cls(
            allow=_strings("allow", DEFAULT_ALLOW),
            deny=_strings("deny", ()),
            max_files_per_change=_int("max_files_per_change", 10),
            max_diff_lines=_int("max_diff_lines", 50),
            source=source,
            raw=dict(data),
        )

    @classmethod
    def load(cls, path: str | Path, engine: str = "mini") -> "Gate":
        p = Path(path)
        if not p.exists():
            return cls(source=f"<missing:{p}>")
        return cls.from_dict(miniyaml.load_file(p, engine=engine), source=str(p))

    # ---------------------------------------------------------------- checks

    def _deny_patterns(self) -> tuple[str, ...]:
        return tuple(self.deny) + tuple(self.hard_deny)

    def check(
        self,
        paths: Iterable[str | Path],
        diff_lines: int | None = None,
    ) -> GateVerdict:
        """Check a proposed self-modification touching ``paths``.

        ``diff_lines`` optionally enforces the report's H5 assumption ("无一次自改 diff
        超过 50 行").
        """
        violations: list[str] = []
        matched: list[str] = []
        cleaned: list[str] = []

        for raw in paths:
            try:
                cleaned.append(normalize(raw))
            except ValueError as exc:
                violations.append(str(exc))

        seen: list[str] = []
        for path in cleaned:
            if path not in seen:
                seen.append(path)

        if len(seen) > self.max_files_per_change:
            violations.append(
                f"too many files in one change: {len(seen)} > {self.max_files_per_change}"
            )

        for path in seen:
            for pattern in self._deny_patterns():
                if match(pattern, path):
                    violations.append(f"{path} matches deny pattern {pattern!r}")
                    break
            else:
                hits = [p for p in self.allow if match(p, path)]
                if hits:
                    matched.extend(hits)
                else:
                    violations.append(
                        f"{path} is not covered by any allow pattern {list(self.allow)!r}"
                    )

        if diff_lines is not None and diff_lines > self.max_diff_lines:
            violations.append(
                f"diff too large: {diff_lines} lines > {self.max_diff_lines} "
                "(minimal-change principle, report H5)"
            )

        return GateVerdict(
            allowed=not violations,
            violations=tuple(dict.fromkeys(violations)),
            matched_allow=tuple(dict.fromkeys(matched)),
            files_checked=len(seen),
        )
