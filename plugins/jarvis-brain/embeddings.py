"""
Опциональный семантический слой поиска для хранилища (vault) и базы знаний (brain).

Почему это нужно: чистый BM25/FTS5 (см. vault.py, db.py) отлично находит документы по точным
словам, но промахивается на перефразировках («где деньги за отпуск» не находит «сумма отпускных»,
если слова не совпадают). Обзор open-source RAG-проектов 2026 года (LightRAG, txtai, AnythingLLM,
Khoj и др.) показывает единый паттерн — **гибридный поиск**: BM25 + векторные эмбеддинги,
объединённые через Reciprocal Rank Fusion (RRF), почти всегда точнее, чем любой из них по одиночке.

Решение здесь — минимально инвазивное и без новых обязательных зависимостей:
  * эмбеддинги считаются **локально через Ollama** (`/api/embed`, модель `nomic-embed-text` —
    маленькая, ~270 МБ, есть почти у всех, кто уже поставил Ollama через `jarvis ollama`);
    если Ollama не установлена/не запущена — модуль тихо отключается, обычный BM25-поиск работает как раньше;
  * векторы хранятся как обычный BLOB (struct.pack) в SQLite — без sqlite-vec/faiss/numpy
    (см. docs/RESEARCH.md, Round 5): для личного хранилища на десятки тысяч кусков файлов
    линейный перебор с чистым Python (~1-5 мс на 1000 векторов) быстрее, чем ставить C-расширение,
    которое на Windows/некоторых Linux-дистрибутивах не всегда имеет колёса;
  * fusion — RRF (k=60, тот же, что в Elasticsearch/OpenSearch reciprocal_rank_fusion по умолчанию),
    простая и не требующая калибровки констант формула, в отличие от взвешенной суммы очков
    разной природы (BM25 score vs cosine similarity).

Публичный API:
  is_available() -> bool                       — Ollama запущена и модель эмбеддингов скачана
  embed(texts: list[str]) -> list[list[float]] | None
  cosine(a, b) -> float
  pack(vec) / unpack(blob)                      — сериализация для BLOB-колонки
  rrf_fuse(rankings: list[list[key]], k=60) -> list[(key, score)]
"""

from __future__ import annotations

import json
import os
import struct
import urllib.error
import urllib.request

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "").strip() or "http://127.0.0.1:11434"
if not OLLAMA_HOST.startswith(("http://", "https://")):
    OLLAMA_HOST = f"http://{OLLAMA_HOST}"
EMBED_MODEL = os.environ.get("JARVIS_EMBED_MODEL", "").strip() or "nomic-embed-text"
_TIMEOUT_PROBE = 1.5
_TIMEOUT_EMBED = 20.0

_availability_cache: bool | None = None


def _post(path: str, payload: dict, timeout: float) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(OLLAMA_HOST.rstrip("/") + path, data=data,
                                  headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _get(path: str, timeout: float) -> dict:
    req = urllib.request.Request(OLLAMA_HOST.rstrip("/") + path)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def is_available(force_recheck: bool = False) -> bool:
    """Ollama запущена локально и модель эмбеддингов уже скачана (не скачивает сама — это может занять минуты)."""
    global _availability_cache
    if _availability_cache is not None and not force_recheck:
        return _availability_cache
    try:
        data = _get("/api/tags", timeout=_TIMEOUT_PROBE)
        names = {m.get("name", "").split(":")[0] for m in data.get("models", [])}
        _availability_cache = EMBED_MODEL.split(":")[0] in names
    except (urllib.error.URLError, OSError, TimeoutError, ValueError):
        _availability_cache = False
    return _availability_cache


def reset_cache() -> None:
    global _availability_cache
    _availability_cache = None


def embed(texts: list[str]) -> list[list[float]] | None:
    """Векторы для списка текстов, или None при любой проблеме (сеть/модель/формат) — вызывающий код
    должен просто продолжить работать с обычным BM25, а не падать."""
    if not texts:
        return []
    try:
        data = _post("/api/embed", {"model": EMBED_MODEL, "input": texts}, timeout=_TIMEOUT_EMBED)
        vecs = data.get("embeddings")
        if not vecs or len(vecs) != len(texts):
            return None
        return vecs
    except (urllib.error.URLError, OSError, TimeoutError, ValueError, KeyError):
        return None


def pack(vec: list[float]) -> bytes:
    return struct.pack(f"<{len(vec)}f", *vec)


def unpack(blob: bytes) -> list[float]:
    n = len(blob) // 4
    return list(struct.unpack(f"<{n}f", blob))


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def rrf_fuse(rankings: list[list], k: int = 60) -> list[tuple]:
    """Reciprocal Rank Fusion: объединяет несколько ранжированных списков ключей (напр. id заметки/куска)
    в один, без нужды нормализовать разнородные очки (BM25 vs cosine). score(d) = sum(1/(k+rank_i(d))).
    Возвращает [(key, fused_score), ...] по убыванию — тот же паттерн, что в Elasticsearch/OpenSearch."""
    scores: dict = {}
    for ranking in rankings:
        for rank, key in enumerate(ranking):
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
