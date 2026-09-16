"""Guard tests for the shell clients: refusals must fire before any network use.

`client/sync_corpus.sh` moves a documentation tree with `rsync --delete`, so its target
guards are the safety net that keeps one corpus from overwriting another. The tests run
the real script with a fake `ssh` first on PATH: reaching ssh exits with a distinct code,
so a guard that stops firing fails here without touching any network.
"""

from __future__ import annotations

import os
import pathlib
import subprocess

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SYNC = REPO_ROOT / "client" / "sync_corpus.sh"
QUERY = REPO_ROOT / "client" / "query.sh"

_FAKE_SSH_RC = 99


def _run(script: pathlib.Path, args: list[str], tmp_path: pathlib.Path) -> subprocess.CompletedProcess[str]:
    stub_dir = tmp_path / "stub-bin"
    stub_dir.mkdir(exist_ok=True)
    ssh_stub = stub_dir / "ssh"
    ssh_stub.write_text(
        f"#!/bin/sh\necho 'ssh was reached' >&2\nexit {_FAKE_SSH_RC}\n",
        encoding="utf-8",
    )
    ssh_stub.chmod(0o755)
    env = {**os.environ, "PATH": f"{stub_dir}:/usr/bin:/bin"}
    return subprocess.run(
        ["bash", str(script), *args],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def test_sync_refuses_unsafe_corpus_name(tmp_path: pathlib.Path) -> None:
    result = _run(
        SYNC,
        ["--corpus", "bad;name", "--source", str(tmp_path), "--host", "guard-test", "--service-dir", "/srv/docs-rag"],
        tmp_path,
    )
    assert result.returncode == 1, result.stderr
    assert "--corpus" in result.stderr


def test_sync_refuses_target_outside_the_corpus_dir(tmp_path: pathlib.Path) -> None:
    result = _run(
        SYNC,
        [
            "--corpus", "demo",
            "--source", str(tmp_path),
            "--host", "guard-test",
            "--service-dir", "/srv/docs-rag",
            "--remote-dir", "/srv/docs-rag/corpus/other",
        ],
        tmp_path,
    )
    assert result.returncode == 1, result.stderr
    assert "--remote-dir" in result.stderr


def test_sync_refuses_trailing_slash_in_target(tmp_path: pathlib.Path) -> None:
    result = _run(
        SYNC,
        [
            "--corpus", "demo",
            "--source", str(tmp_path),
            "--host", "guard-test",
            "--service-dir", "/srv/docs-rag",
            "--remote-dir", "/srv/docs-rag/corpus/demo/",
        ],
        tmp_path,
    )
    assert result.returncode == 1, result.stderr
    assert "--remote-dir" in result.stderr


def test_sync_requires_corpus_argument(tmp_path: pathlib.Path) -> None:
    result = _run(SYNC, ["--source", str(tmp_path)], tmp_path)
    assert result.returncode == 2, result.stderr
    assert "--corpus" in result.stderr


def test_help_prints_the_header_block_only(tmp_path: pathlib.Path) -> None:
    for script, first_line in ((SYNC, "Push a documentation tree"), (QUERY, "Query a docs-rag corpus")):
        result = _run(script, ["--help"], tmp_path)
        assert result.returncode == 0, result.stderr
        assert result.stdout.startswith(first_line), result.stdout
        # the comment block ends at the first non-comment line: no shell code leaks into --help
        assert "set -euo" not in result.stdout
