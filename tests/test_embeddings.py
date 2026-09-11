"""embeddings.py — семантический слой (RRF-fusion, cosine, pack/unpack, доступность Ollama)."""

from __future__ import annotations

import importlib.util
import sys
import urllib.error
from pathlib import Path

import pytest

PLUGINS = Path(__file__).resolve().parent.parent / "plugins"


def _load():
    spec = importlib.util.spec_from_file_location("emb_test_mod", PLUGINS / "jarvis-brain" / "embeddings.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["emb_test_mod"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


@pytest.fixture()
def emb():
    mod = _load()
    mod.reset_cache()
    yield mod
    mod.reset_cache()


def test_pack_unpack_roundtrip(emb):
    vec = [0.1, -0.2, 3.5, 0.0]
    blob = emb.pack(vec)
    out = emb.unpack(blob)
    assert len(out) == len(vec)
    for a, b in zip(vec, out):
        assert abs(a - b) < 1e-6


def test_cosine_basic(emb):
    assert emb.cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert emb.cosine([1, 0], [0, 1]) == pytest.approx(0.0)
    assert emb.cosine([], [1, 2]) == 0.0
    assert emb.cosine([1, 2], [1, 2, 3]) == 0.0  # разная размерность — не бросает
    assert emb.cosine([0, 0], [1, 1]) == 0.0  # нулевой вектор — не делит на ноль


def test_rrf_fuse_prefers_items_ranked_high_in_both_lists(emb):
    # "b" — вторая по BM25, но первая по семантике → в объединении должна обойти "a" (только BM25) при равном охвате
    bm25 = ["a", "b", "c"]
    semantic = ["b", "d"]
    fused = emb.rrf_fuse([bm25, semantic])
    keys = [k for k, _ in fused]
    assert keys[0] == "b"  # встречается в обоих списках, причём высоко


def test_rrf_fuse_single_list_preserves_order(emb):
    fused = emb.rrf_fuse([["x", "y", "z"]])
    assert [k for k, _ in fused] == ["x", "y", "z"]


def test_is_available_false_when_ollama_unreachable(emb, monkeypatch):
    def boom(*a, **kw):
        raise urllib.error.URLError("no route")
    monkeypatch.setattr(emb, "_get", boom)
    assert emb.is_available() is False


def test_is_available_true_when_model_present(emb, monkeypatch):
    monkeypatch.setattr(emb, "_get", lambda path, timeout: {"models": [{"name": "nomic-embed-text:latest"}]})
    assert emb.is_available() is True


def test_is_available_caches_until_reset(emb, monkeypatch):
    calls = {"n": 0}

    def fake_get(path, timeout):
        calls["n"] += 1
        return {"models": [{"name": "nomic-embed-text:latest"}]}
    monkeypatch.setattr(emb, "_get", fake_get)
    assert emb.is_available() is True
    assert emb.is_available() is True
    assert calls["n"] == 1  # закешировано
    emb.reset_cache()
    assert emb.is_available() is True
    assert calls["n"] == 2


def test_embed_returns_none_on_network_error(emb, monkeypatch):
    def boom(*a, **kw):
        raise urllib.error.URLError("down")
    monkeypatch.setattr(emb, "_post", boom)
    assert emb.embed(["hello"]) is None


def test_embed_returns_none_on_mismatched_length(emb, monkeypatch):
    monkeypatch.setattr(emb, "_post", lambda path, payload, timeout: {"embeddings": [[0.1, 0.2]]})
    assert emb.embed(["a", "b"]) is None  # 2 текста, но 1 вектор — не выдаём частичный результат


def test_embed_happy_path(emb, monkeypatch):
    monkeypatch.setattr(emb, "_post", lambda path, payload, timeout: {"embeddings": [[0.1, 0.2], [0.3, 0.4]]})
    out = emb.embed(["a", "b"])
    assert out == [[0.1, 0.2], [0.3, 0.4]]


def test_embed_empty_input_returns_empty_list(emb):
    assert emb.embed([]) == []
