"""Packaging: the 4 runtime KBs must resolve from inside the installed package
(no repo checkout), and $SYLLABUS_CLASSIFIER_CONFIG_DIR must override them.
This is what makes `pip install syllabus-classifier` usable in gwatop-backend."""
from syllabus_classifier.common import config as cfg

_RUNTIME_KBS = ("period_timetables.yaml", "academic_calendars.yaml",
                "school_dictionary.yaml", "label_dictionary.yaml")


def test_runtime_kbs_are_bundled_in_package():
    d = cfg._packaged_config_dir()
    assert d is not None, "packaged config dir not resolvable"
    for name in _RUNTIME_KBS:
        assert (d / name).exists(), f"{name} missing from package config/"


def test_load_config_resolves_packaged_kb():
    assert "timetables" in cfg.load_config("period_timetables.yaml")
    assert "calendars" in cfg.load_config("academic_calendars.yaml")


def test_env_override_takes_precedence(tmp_path, monkeypatch):
    fake = tmp_path / "period_timetables.yaml"
    fake.write_text("timetables:\n  __override_marker__: {}\n", encoding="utf-8")
    monkeypatch.setenv("SYLLABUS_CLASSIFIER_CONFIG_DIR", str(tmp_path))
    cfg.load_config.cache_clear()
    try:
        loaded = cfg.load_config("period_timetables.yaml")
        assert "__override_marker__" in loaded.get("timetables", {})
    finally:
        cfg.load_config.cache_clear()  # env is unset by monkeypatch teardown
