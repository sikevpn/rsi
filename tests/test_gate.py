"""S0.2 / S4.2 — the machine-enforced self-modification gate."""

from __future__ import annotations

from pathlib import Path

import pytest

from rsi.gate import DEFAULT_ALLOW, HARD_DENY, Gate, match, normalize

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize(
    "pattern,path,expected",
    [
        ("prompts/*.md", "prompts/PROMPT_build.md", True),
        ("prompts/*.md", "prompts/nested/x.md", False),   # '*' does not span '/'
        ("rsi/**", "rsi/outer.py", True),
        ("rsi/**", "rsi/pkg/deep/mod.py", True),
        ("**/gate.yaml", "sub/dir/gate.yaml", True),
        (".env.*", ".env.local", True),
        ("memories.md", "memories.md", True),
        ("memories.md", "other/memories.md", False),
    ],
)
def test_glob_semantics(pattern, path, expected):
    assert match(pattern, path) is expected


def test_allowlisted_paths_pass():
    gate = Gate()
    verdict = gate.check(["prompts/PROMPT_build.md", "memories.md"], diff_lines=12)
    assert verdict.allowed, verdict.explain()
    assert set(verdict.matched_allow) == {"prompts/*.md", "memories.md"}
    assert verdict.files_checked == 2


def test_unlisted_path_is_blocked():
    verdict = Gate().check(["src/app.py"])
    assert not verdict.allowed
    assert any("not covered by any allow pattern" in v for v in verdict.violations)


@pytest.mark.parametrize(
    "path",
    [".env", ".env.production", "secrets/key.pem", "auth/token.json", "migrations/0001.sql"],
)
def test_report_blacklist_is_blocked(path):
    assert not Gate().check([path]).allowed


def test_hard_deny_survives_a_gate_yaml_that_tries_to_widen_it():
    """The gate file must not be able to authorise edits to itself or to the orchestrator."""
    hostile = {
        "allow": ["**"],
        "deny": [],
        "hard_deny": [],          # attempting to clear the hardcoded list
        "max_diff_lines": 100000,
    }
    gate = Gate.from_dict(hostile, source="hostile.yaml")
    assert gate.hard_deny == HARD_DENY      # constructor default is not overridden
    for path in ("gate.yaml", "rsi/outer.py", "rsi/gate.py", ".env", "secrets/k.pem"):
        assert not gate.check([path]).allowed, path


def test_gate_yaml_itself_is_always_denied():
    assert not Gate().check(["gate.yaml"]).allowed
    assert not Gate().check(["nested/gate.yaml"]).allowed


def test_orchestrator_source_is_always_denied():
    assert not Gate().check(["rsi/inner.py"]).allowed


@pytest.mark.parametrize("bad", ["/etc/passwd", "../escape.md", "a/../../b.md", "C:\\x.md", ""])
def test_path_normalization_rejects_escapes(bad):
    with pytest.raises(ValueError):
        normalize(bad)


def test_normalize_converts_windows_separators():
    assert normalize("prompts\\PROMPT_build.md") == "prompts/PROMPT_build.md"


def test_per_change_file_cap():
    gate = Gate(allow=DEFAULT_ALLOW, max_files_per_change=2)
    paths = ["prompts/a.md", "prompts/b.md", "prompts/c.md"]
    verdict = gate.check(paths)
    assert not verdict.allowed
    assert any("too many files" in v for v in verdict.violations)


def test_h5_minimal_change_diff_cap():
    """Report H5: no self-modification diff may exceed 50 lines."""
    gate = Gate()
    assert gate.check(["memories.md"], diff_lines=50).allowed
    verdict = gate.check(["memories.md"], diff_lines=51)
    assert not verdict.allowed
    assert any("minimal-change principle" in v for v in verdict.violations)


def test_shipped_gate_yaml_loads_and_enforces():
    gate = Gate.load(REPO_ROOT / "loop-project" / "gate.yaml")
    assert gate.max_diff_lines == 50
    assert gate.check(["prompts/PROMPT_build.md"], diff_lines=3).allowed
    assert not gate.check(["IMPLEMENTATION_PLAN.md"]).allowed   # project-level deny
    assert not gate.check(["receipts/receipts.jsonl"]).allowed


def test_missing_gate_file_falls_back_to_defaults(tmp_path: Path):
    gate = Gate.load(tmp_path / "absent.yaml")
    assert gate.allow == DEFAULT_ALLOW
    assert not gate.check(["src/x.py"]).allowed
