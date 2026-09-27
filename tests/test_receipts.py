"""S3.1 — SHA-256-pinned receipts with a closed terminal-state enumeration."""

from __future__ import annotations

import json

import pytest

from rsi.receipts import (
    ATTRIBUTIONS,
    TERMINAL_STATES,
    Receipt,
    append_receipt,
    compute_sha256,
    read_receipts,
    read_recent,
    summarize,
    verify_integrity,
)


def test_terminal_state_enumeration_is_closed():
    assert "COMPLETED" in TERMINAL_STATES
    assert "KILL_SWITCH" in TERMINAL_STATES
    with pytest.raises(ValueError):
        Receipt(task="t", terminal_state="PROBABLY_DONE")


def test_attribution_enumeration_is_closed():
    assert "LOOP_DESIGN" in ATTRIBUTIONS
    with pytest.raises(ValueError):
        Receipt(task="t", terminal_state="FAILED", attribution="VIBES")


def test_sha256_is_pinned_and_reproducible():
    """Identical inputs (timestamp included) must produce an identical pin."""
    kwargs = dict(
        task="T1: x",
        terminal_state="COMPLETED",
        iterations=2,
        tokens=10,
        ts="2026-09-28T00:00:00+00:00",
    )
    a = Receipt(**kwargs)
    b = Receipt(**kwargs)
    assert a.sha256 == b.sha256
    assert len(a.sha256) == 64
    assert compute_sha256(a.payload()) == a.sha256


def test_distinct_timestamps_produce_distinct_pins():
    a = Receipt(task="T1: x", terminal_state="COMPLETED", ts="2026-09-28T00:00:00+00:00")
    b = Receipt(task="T1: x", terminal_state="COMPLETED", ts="2026-09-28T00:00:01+00:00")
    assert a.sha256 != b.sha256


def test_sha256_excludes_itself_from_the_preimage():
    r = Receipt(task="T1: x", terminal_state="FAILED")
    payload = r.payload()
    assert "sha256" in payload
    body = {k: v for k, v in payload.items() if k != "sha256"}
    assert compute_sha256(body) == r.sha256


def test_verify_integrity_detects_tampering(tmp_path):
    path = tmp_path / "receipts.jsonl"
    r = Receipt(task="T1: x", terminal_state="FAILED", test_pass=False)
    append_receipt(path, r)

    raw = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert verify_integrity(raw)

    raw["test_pass"] = True          # rewrite history: the run now looks successful
    path.write_text(json.dumps(raw) + "\n", encoding="utf-8")
    assert not verify_integrity(json.loads(path.read_text(encoding="utf-8").splitlines()[0]))


def test_append_and_read_roundtrip(tmp_path):
    path = tmp_path / "r.jsonl"
    for i in range(4):
        append_receipt(path, Receipt(task=f"T{i}", terminal_state="COMPLETED", iterations=i))
    rows = read_receipts(path)
    assert [r["task"] for r in rows] == ["T0", "T1", "T2", "T3"]
    assert [r["task"] for r in read_recent(path, 2)] == ["T2", "T3"]
    assert read_recent(path, 0) == []


def test_read_missing_file_is_empty(tmp_path):
    assert read_receipts(tmp_path / "nope.jsonl") == []


def test_summarize_metrics():
    rows = [
        {"terminal_state": "COMPLETED", "iterations": 2, "tokens": 100, "cost_usd": 0.1},
        {"terminal_state": "FAILED", "iterations": 4, "tokens": 300, "cost_usd": 0.3},
    ]
    s = summarize(rows)
    assert s["runs"] == 2
    assert s["completed"] == 1
    assert s["completion_rate"] == 0.5
    assert s["avg_iterations"] == 3.0
    assert s["total_tokens"] == 400
    assert s["total_cost_usd"] == pytest.approx(0.4)


def test_summarize_empty_is_safe():
    s = summarize([])
    assert s["runs"] == 0 and s["completion_rate"] == 0.0 and s["avg_iterations"] == 0.0


def test_evidence_is_json_normalised():
    r = Receipt(
        task="T1", terminal_state="FAILED", evidence={"cheat_detected": True, "n": 1}
    )
    assert json.loads(r.to_json())["evidence"]["cheat_detected"] is True
