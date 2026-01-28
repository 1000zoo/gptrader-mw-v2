import pytest

pytest.importorskip("fastapi")
pytest.importorskip("loguru")

from src.ops.mw.ops_mw import _validate_ops_token


def test_ops_token_denied(monkeypatch):
    monkeypatch.setenv("OPS_TOKEN", "secret")
    with pytest.raises(Exception):
        _validate_ops_token("wrong")
