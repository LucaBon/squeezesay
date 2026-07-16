"""Tests for localvoice/appdata.py: env-var namespace with legacy fallback,
data-dir resolution order, and atomic JSON read/write fail-open behavior."""

import os

import appdata


# -- env() -------------------------------------------------------------------

def test_env_reads_primary_prefix():
    environ = {f"{appdata.PRIMARY_PREFIX}_LMS": "http://x:9000"}
    assert appdata.env("LMS", environ=environ) == "http://x:9000"


def test_env_default_when_missing():
    assert appdata.env("LMS", default="fallback", environ={}) == "fallback"
    assert appdata.env("LMS", environ={}) is None


def test_env_legacy_fallback(monkeypatch, capsys):
    monkeypatch.setattr(appdata, "LEGACY_PREFIX", "OLDNAME")
    monkeypatch.setattr(appdata, "_warned_legacy", set())
    environ = {"OLDNAME_PORT": "9999"}
    assert appdata.env("PORT", environ=environ) == "9999"
    assert "deprecata" in capsys.readouterr().out
    # The deprecation note prints once per variable, not once per read.
    assert appdata.env("PORT", environ=environ) == "9999"
    assert capsys.readouterr().out == ""


def test_env_primary_wins_over_legacy(monkeypatch):
    monkeypatch.setattr(appdata, "LEGACY_PREFIX", "OLDNAME")
    environ = {f"{appdata.PRIMARY_PREFIX}_PORT": "1", "OLDNAME_PORT": "2"}
    assert appdata.env("PORT", environ=environ) == "1"


# -- data_dir() ---------------------------------------------------------------

def test_data_dir_cli_wins(tmp_path):
    target = str(tmp_path / "cli-dir")
    environ = {f"{appdata.PRIMARY_PREFIX}_DATA_DIR": str(tmp_path / "env-dir")}
    assert appdata.data_dir(target, environ=environ) == target
    assert os.path.isdir(target)


def test_data_dir_env_fallback(tmp_path):
    target = str(tmp_path / "env-dir")
    environ = {f"{appdata.PRIMARY_PREFIX}_DATA_DIR": target}
    assert appdata.data_dir(None, environ=environ) == target
    assert os.path.isdir(target)


def test_data_dir_platform_default(tmp_path, monkeypatch):
    # Senza CLI né env si ripiega sulla cartella di piattaforma: qui basta
    # verificare che usi la base giusta (APPDATA su Windows, XDG altrove).
    if os.name == "nt":
        environ = {"APPDATA": str(tmp_path)}
        expected = os.path.join(str(tmp_path), appdata.APP_DIR_NAME)
    else:
        environ = {"XDG_DATA_HOME": str(tmp_path)}
        expected = os.path.join(str(tmp_path), appdata.APP_DIR_NAME.lower())
    assert appdata.data_dir(None, environ=environ) == expected
    assert os.path.isdir(expected)


# -- JSON helpers -------------------------------------------------------------

def test_json_roundtrip(tmp_path):
    path = str(tmp_path / "state.json")
    appdata.atomic_write_json(path, {"k": "à", "n": [1, 2]})
    assert appdata.read_json(path) == {"k": "à", "n": [1, 2]}
    assert not os.path.exists(path + ".tmp")  # no leftover temp file


def test_read_json_fails_open(tmp_path):
    missing = str(tmp_path / "missing.json")
    assert appdata.read_json(missing) is None
    assert appdata.read_json(missing, default={}) == {}
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{not json", encoding="utf-8")
    assert appdata.read_json(str(corrupt), default=[]) == []


def test_atomic_write_replaces_existing(tmp_path):
    path = str(tmp_path / "state.json")
    appdata.atomic_write_json(path, {"v": 1})
    appdata.atomic_write_json(path, {"v": 2})
    assert appdata.read_json(path) == {"v": 2}
