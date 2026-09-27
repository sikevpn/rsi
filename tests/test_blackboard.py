"""S1.1 — markdown blackboard parsing and write-back."""

from __future__ import annotations

from rsi import blackboard

PLAN = """# Plan

- [ ] (T1) first task
- [x] (T2) already done
- [ ] (T3) third
* [ ] star bullet task
- not a task
- [ ] no id here
"""


def test_parse_plan_reads_ids_marks_and_line_numbers():
    tasks = blackboard.parse_plan(PLAN)
    assert [t.id for t in tasks] == ["T1", "T2", "T3", "T4", "T5"]
    assert [t.done for t in tasks] == [False, True, False, False, False]
    assert tasks[0].line_no == 3
    assert tasks[0].text == "first task"
    assert tasks[4].text == "no id here"      # auto-assigned id T5


def test_open_and_first_open_task():
    tasks = blackboard.parse_plan(PLAN)
    assert [t.id for t in blackboard.open_tasks(tasks)] == ["T1", "T3", "T4", "T5"]
    assert blackboard.first_open_task(tasks).id == "T1"
    assert blackboard.first_open_task([t for t in tasks if t.done]) is None


def test_mark_done_flips_exactly_one_checkbox(tmp_path):
    path = tmp_path / "IMPLEMENTATION_PLAN.md"
    path.write_text(PLAN, encoding="utf-8")
    assert blackboard.mark_done(path, "T3") is True

    text = path.read_text(encoding="utf-8")
    assert "- [ ] (T1) first task" in text
    assert "- [x] (T3) third" in text
    assert blackboard.mark_done(path, "T3") is False   # idempotent


def test_mark_done_unknown_id_changes_nothing(tmp_path):
    path = tmp_path / "IMPLEMENTATION_PLAN.md"
    path.write_text(PLAN, encoding="utf-8")
    before = path.read_text(encoding="utf-8")
    assert blackboard.mark_done(path, "T99") is False
    assert path.read_text(encoding="utf-8") == before


def test_load_memories_truncates_from_the_front(tmp_path):
    """Newest notes live at the bottom, so truncation must drop the *oldest*."""
    path = tmp_path / "memories.md"
    path.write_text("OLDEST LINE\n" + "x" * 50 + "\nNEWEST LINE\n", encoding="utf-8")
    loaded = blackboard.load_memories(path, max_chars=40)
    assert loaded.endswith("NEWEST LINE")
    assert "OLDEST LINE" not in loaded
    assert loaded.startswith("…")


def test_load_memories_missing_file_is_empty(tmp_path):
    assert blackboard.load_memories(tmp_path / "nope.md") == ""
