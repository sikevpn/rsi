"""S0.4 — the execution-backend adapter layer, including a real subprocess spawn."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from rsi.backend import (
    AgentRequest,
    CliBackend,
    StubBackend,
    StubTurn,
    _extract_usage,
    detect_backend,
)


def _req(cwd: Path, mode: str = "build") -> AgentRequest:
    return AgentRequest(mode=mode, prompt="do it", cwd=cwd, task="T1", iteration=1)


def test_stub_backend_writes_files_and_done(tmp_path):
    backend = StubBackend(
        [StubTurn(files={"a/b.py": "x = 1\n"}, done={"status": "done", "test_exit_code": 0})]
    )
    result = backend.run(_req(tmp_path))
    assert result.ok and result.exit_code == 0 and result.backend == "stub"
    assert (tmp_path / "a" / "b.py").read_text() == "x = 1\n"
    assert json.loads((tmp_path / "DONE.json").read_text())["test_exit_code"] == 0


def test_stub_backend_clears_a_stale_done_signal(tmp_path):
    """A fresh-context turn that produced nothing must not inherit DONE.json."""
    (tmp_path / "DONE.json").write_text('{"status":"done"}', encoding="utf-8")
    backend = StubBackend([StubTurn(files={"x.txt": "hi"})])
    backend.run(_req(tmp_path))
    assert not (tmp_path / "DONE.json").exists()


def test_stub_backend_records_requests_for_context_assertions(tmp_path):
    backend = StubBackend([StubTurn(), StubTurn()])
    backend.run(_req(tmp_path, "build"))
    backend.run(_req(tmp_path, "audit"))
    assert [c.mode for c in backend.calls] == ["build", "audit"]


def test_stub_backend_spawn_error(tmp_path):
    backend = StubBackend([StubTurn(spawn_error="claude: command not found")])
    result = backend.run(_req(tmp_path))
    assert not result.ok
    assert result.exit_code == 127
    assert result.spawn_error == "claude: command not found"


def test_stub_backend_flags_script_exhaustion(tmp_path):
    backend = StubBackend([StubTurn()])
    first = backend.run(_req(tmp_path))
    second = backend.run(_req(tmp_path))
    assert first.script_exhausted is True
    assert second.script_exhausted is True
    assert second.stderr == "[stub] no script configured"


def test_cli_backend_spawns_a_real_subprocess_and_recovers_exit_code(tmp_path):
    """Genuinely exercises the subprocess path the report's §5.3 depends on."""
    script = tmp_path / "fake-cli.sh"
    script.write_text(
        "#!/bin/sh\n"
        "cat > /dev/null\n"                      # consume the piped prompt
        "echo '{\"usage\":{\"total_tokens\":42}}'\n"
        "echo '{\"total_cost_usd\":0.5}'\n"
        "exit 7\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)

    backend = CliBackend(argv=[str(script)])
    result = backend.run(_req(tmp_path))
    assert result.exit_code == 7
    assert result.ok is False
    assert result.tokens == 42
    assert result.cost_usd == 0.5
    assert backend.name == "fake-cli.sh"


def test_cli_backend_reports_missing_binary_as_spawn_error(tmp_path):
    backend = CliBackend(argv=[str(tmp_path / "definitely-not-here")])
    result = backend.run(_req(tmp_path))
    assert result.exit_code == 127
    assert "not found on PATH" in result.spawn_error


def test_cli_backend_rejects_empty_argv():
    with pytest.raises(ValueError):
        CliBackend(argv=[])


def test_extract_usage_tolerates_noise():
    stdout = (
        "some banner text\n"
        '{"type":"assistant","usage":{"total_tokens":10}}\n'
        "not json {\n"
        '{"total_cost_usd":0.25}\n'
    )
    assert _extract_usage(stdout) == (10, 0.25)
    assert _extract_usage("") == (0, 0.0)


def test_detect_backend_returns_none_when_no_cli_is_installed(monkeypatch):
    monkeypatch.setattr("rsi.backend.shutil.which", lambda _name: None)
    assert detect_backend() == "none"


def test_detect_backend_finds_first_candidate(monkeypatch):
    monkeypatch.setattr(
        "rsi.backend.shutil.which", lambda name: "/usr/bin/claude" if name == "claude" else None
    )
    assert detect_backend() == "claude"


def test_backend_protocol_is_satisfied_by_both_implementations(tmp_path):
    from rsi.backend import Backend

    assert isinstance(StubBackend(), Backend)
    assert isinstance(CliBackend(argv=["true"]), Backend)
