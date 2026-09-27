"""S0.3 — zero-dependency YAML subset parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from rsi import miniyaml

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_parses_shipped_gate_yaml():
    data = miniyaml.load_file(REPO_ROOT / "loop-project" / "gate.yaml")
    assert data["allow"] == ["prompts/*.md", "memories.md", "config/*.yaml", "skills/*.md"]
    assert data["deny"] == ["IMPLEMENTATION_PLAN.md", "receipts/**", "proposals.md"]
    assert data["max_files_per_change"] == 10
    assert data["max_diff_lines"] == 50


def test_parses_shipped_loop_config_types():
    data = miniyaml.load_file(REPO_ROOT / "loop-project" / "config" / "loop.yaml")
    assert data["max_iterations"] == 50
    assert isinstance(data["max_cost_usd"], float)
    assert data["test_commands"] == ["python3 -m pytest -q"]
    assert data["auditor_enabled"] is True
    assert data["autonomy_level"] == "L1"
    assert data["max_tasks"] == 0


def test_nested_mapping_and_list_of_mappings():
    text = (
        "root:\n"
        "  name: demo\n"
        "  items:\n"
        "    - id: a\n"
        "      weight: 2\n"
        "    - id: b\n"
        "      weight: 3\n"
    )
    assert miniyaml.loads(text) == {
        "root": {"name": "demo", "items": [{"id": "a", "weight": 2}, {"id": "b", "weight": 3}]}
    }


def test_scalars_flow_list_and_quotes():
    text = (
        "n: 42\n"
        "f: 1.5e2\n"
        "b: yes\n"
        "off_: off\n"
        "nil: ~\n"
        "empty:\n"
        "flow: [a, b, 3]\n"
        "quoted: 'true'\n"
        "hash: \"value # not a comment\"\n"
    )
    data = miniyaml.loads(text)
    assert data["n"] == 42
    assert data["f"] == 150.0
    assert data["b"] is True
    assert data["off_"] is False
    assert data["nil"] is None
    assert data["empty"] is None
    assert data["flow"] == ["a", "b", 3]
    assert data["quoted"] == "true"
    assert data["hash"] == "value # not a comment"


def test_inline_comment_outside_quotes_is_stripped():
    assert miniyaml.loads("key: value  # trailing note\n") == {"key": "value"}


@pytest.mark.parametrize(
    "text",
    [
        "root:\n\tkey: v\n",                       # tab indentation
        "root:\n  a: 1\n b: 2\n",                  # dedent to a non-matching level
        "just a bare scalar\nmore\n",              # trailing content
    ],
)
def test_out_of_subset_raises(text):
    with pytest.raises(miniyaml.MiniYAMLError):
        miniyaml.loads(text)


def test_agrees_with_pyyaml_on_shipped_files():
    """Cross-check: the zero-dep parser must not drift from PyYAML on what we ship."""
    pytest.importorskip("yaml")
    for rel in ("loop-project/gate.yaml", "loop-project/config/loop.yaml"):
        path = REPO_ROOT / rel
        text = path.read_text(encoding="utf-8")
        assert miniyaml.loads(text, engine="mini") == miniyaml.loads(text, engine="pyyaml")


def test_dumps_scalar_roundtrip():
    for value in (None, True, False, 0, 3.5, "plain", "true", "", "has # hash", "42"):
        rendered = miniyaml.dumps_scalar(value)
        assert miniyaml.loads(f"k: {rendered}\n")["k"] == value
