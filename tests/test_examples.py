"""The runnable examples must keep working — they are documentation."""

import sys
from pathlib import Path

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


def _load(name: str):
    if str(EXAMPLES_DIR) not in sys.path:
        sys.path.insert(0, str(EXAMPLES_DIR))
    return __import__(name)


def test_quickstart_runs(tmp_path, capsys):
    _load("quickstart").main(db_path=str(tmp_path / "team.db"))
    out = capsys.readouterr().out
    assert "warm the cache before deploying the pricing service" in out


def test_keyfile_reuse_runs(tmp_path, capsys):
    _load("keyfile_reuse").main(keyfile=tmp_path / "scout.key")
    out = capsys.readouterr().out
    assert "same author across sessions" in out
