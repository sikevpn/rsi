"""The markdown blackboard: IMPLEMENTATION_PLAN.md and memories.md.

Report §3.4 "文件即记忆": progress lives in a checkbox list that every fresh-context
iteration re-reads.  Parsing is deliberately strict — a line that does not match the
checkbox grammar is ignored rather than guessed at.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

__all__ = ["Task", "parse_plan", "open_tasks", "first_open_task", "mark_done", "load_memories"]

_CHECKBOX = re.compile(r"^(?P<indent>\s*)[-*]\s+\[(?P<mark>[ xX])\]\s+(?P<text>.+?)\s*$")
_ID_TOKEN = re.compile(r"^(?:\(|\[)(?P<id>[A-Za-z0-9_.-]+)(?:\)|\])\s+(?P<rest>.+)$")


@dataclass(frozen=True)
class Task:
    id: str
    text: str
    done: bool
    line_no: int  # 1-based


def parse_plan(text: str) -> list[Task]:
    tasks: list[Task] = []
    auto = 0
    for idx, line in enumerate(text.splitlines(), start=1):
        m = _CHECKBOX.match(line)
        if not m:
            continue
        auto += 1
        body = m.group("text").strip()
        idm = _ID_TOKEN.match(body)
        if idm:
            task_id = idm.group("id")
            body = idm.group("rest").strip()
        else:
            task_id = f"T{auto}"
        tasks.append(
            Task(id=task_id, text=body, done=m.group("mark").lower() == "x", line_no=idx)
        )
    return tasks


def open_tasks(tasks: list[Task]) -> list[Task]:
    return [t for t in tasks if not t.done]


def first_open_task(tasks: list[Task]) -> Task | None:
    remaining = open_tasks(tasks)
    return remaining[0] if remaining else None


def mark_done(path: str | Path, task_id: str) -> bool:
    """Flip one checkbox from ``[ ]`` to ``[x]``.  Returns True if a line was rewritten."""
    p = Path(path)
    lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
    changed = False
    for idx, line in enumerate(lines):
        m = _CHECKBOX.match(line.rstrip("\n"))
        if not m:
            continue
        body = m.group("text").strip()
        idm = _ID_TOKEN.match(body)
        candidate = idm.group("id") if idm else None
        if candidate != task_id:
            continue
        if m.group("mark").lower() == "x":
            return False
        newline = "\n" if line.endswith("\n") else ""
        lines[idx] = (
            f"{m.group('indent')}- [x] {m.group('text')}{newline}"
        )
        changed = True
        break
    if changed:
        p.write_text("".join(lines), encoding="utf-8")
    return changed


def load_memories(path: str | Path, max_chars: int = 4000) -> str:
    """Return memory text truncated from the *front* — newest notes live at the bottom."""
    p = Path(path)
    if not p.exists():
        return ""
    text = p.read_text(encoding="utf-8").strip()
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    return "…(older memories truncated)\n" + text[-max_chars:]
