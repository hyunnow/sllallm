"""api.extract_syllabus — the stable host-app entry point (GwaTop port).

Contract: always returns {record, compiled, quality, notes} and never raises on
an unreadable/unsupported file (the host inspects `quality` to decide fallback).
Running it also exercises packaged-KB loading (compile_record builds a KBResolver
from the bundled config), so this doubles as a pip-install smoke test.
"""
from syllabus_classifier.api import extract_syllabus


def _assert_contract(out):
    assert set(out) >= {"record", "compiled", "quality", "notes"}
    c = out["compiled"]
    assert set(c) >= {"confirmed_events", "weekly_timetable", "needs_review_events", "stats"}
    assert isinstance(c["confirmed_events"], list)
    assert isinstance(out["notes"], list)


def test_unsupported_file_returns_contract_without_raising(tmp_path):
    f = tmp_path / "syllabus.txt"
    f.write_text("아무 내용", encoding="utf-8")
    out = extract_syllabus(str(f), classifier="heuristic")
    _assert_contract(out)
    assert out["quality"] == "failed"        # host will fall back to OpenAI
    assert out["compiled"]["stats"]["confirmed"] == 0


def test_missing_file_returns_contract_without_raising(tmp_path):
    out = extract_syllabus(str(tmp_path / "does_not_exist.pdf"), classifier="heuristic")
    _assert_contract(out)
    assert out["quality"] in ("failed", "needs_ocr")
