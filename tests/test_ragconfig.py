"""Unit tests for the external corpus config loader.

No tenant-specific corpus exists in code: corpora.json is the only source and it must
declare every required key, so a typo or a missing file fails loudly instead of silently
serving some other corpus.
"""

from __future__ import annotations

import json
import pathlib

import pytest

import ragconfig

VALID = {
    "corpus_dir": "corpus/x",
    "data_dir": "data-x",
    "top_files": ["AGENTS.md"],
    "doc_root_files": ["README.md"],
    "roots": ["docs/notes"],
    "exclude_dirs": ["archive"],
}


def _write(tmp_path: pathlib.Path, payload: object) -> None:
    (tmp_path / "corpora.json").write_text(json.dumps(payload), encoding="utf-8")


def test_missing_config_file_fails_loud(tmp_path: pathlib.Path, monkeypatch) -> None:
    monkeypatch.setattr(ragconfig, "RAG_DIR", tmp_path)
    with pytest.raises(RuntimeError):
        ragconfig.load_corpora()


def test_corpora_come_from_config_file(tmp_path: pathlib.Path, monkeypatch) -> None:
    _write(tmp_path, {"_comment": ["ignored"], "x": VALID, "y": {**VALID, "data_dir": "data-y"}})
    monkeypatch.setattr(ragconfig, "RAG_DIR", tmp_path)
    corpora = ragconfig.load_corpora()

    assert sorted(corpora) == ["x", "y"]
    assert corpora["x"] == VALID
    assert corpora["y"]["data_dir"] == "data-y"
    assert "_comment" not in corpora


def test_missing_required_key_fails_loud(tmp_path: pathlib.Path, monkeypatch) -> None:
    _write(tmp_path, {"x": {key: value for key, value in VALID.items() if key != "roots"}})
    monkeypatch.setattr(ragconfig, "RAG_DIR", tmp_path)
    with pytest.raises(RuntimeError):
        ragconfig.load_corpora()


def test_invalid_config_fails_loud(tmp_path: pathlib.Path, monkeypatch) -> None:
    monkeypatch.setattr(ragconfig, "RAG_DIR", tmp_path)
    config = tmp_path / "corpora.json"

    # 解析失敗 = RuntimeError；型別錯誤 = TypeError（違約的型別不該報成執行期錯誤）
    config.write_text("{ not json", encoding="utf-8")
    with pytest.raises(RuntimeError):
        ragconfig.load_corpora()

    config.write_text('["a"]', encoding="utf-8")
    with pytest.raises(TypeError):
        ragconfig.load_corpora()

    config.write_text('{"broken": []}', encoding="utf-8")
    with pytest.raises(TypeError):
        ragconfig.load_corpora()
