"""Text embeddings, metered and cached. Generic on purpose: any feature that compares texts by
meaning (retrieval.py) reads them from here.

Every call goes through `access.openai_embedding`, so a pass pays for it and the public demo
without a pass is refused. A vector is cached on disk by a hash of (model, text), so a re-run of the
same pages costs nothing.
"""
import contextlib
import hashlib
import math
import sqlite3
from array import array

import access
import reports

MODEL = "text-embedding-3-small"
BATCH = 256        # texts per request, well under the API's limit
TIMEOUT = 60


def _key(model: str, text: str) -> str:
    return hashlib.sha256(f"{model}\0{text}".encode()).hexdigest()


def _path():
    return reports.DATA / "embeddings.db"


@contextlib.contextmanager
def _cache():
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    try:
        with conn:
            conn.execute("CREATE TABLE IF NOT EXISTS vectors (key TEXT PRIMARY KEY, v BLOB NOT NULL)")
            yield conn
    finally:
        conn.close()


def _vector(item) -> list[float]:
    return item["embedding"] if isinstance(item, dict) else item.embedding


def embed(texts: list[str], model: str = MODEL) -> list[list[float]]:
    """One vector per text, in order. Only texts not already cached are sent."""
    keys = [_key(model, t) for t in texts]
    with _cache() as c:
        have = {k: array("f", v).tolist() for k, v in c.execute(
            f"SELECT key, v FROM vectors WHERE key IN ({','.join('?' * len(set(keys)))})", list(set(keys)))} \
            if keys else {}
    todo = list(dict.fromkeys(t for t, k in zip(texts, keys) if k not in have))
    for i in range(0, len(todo), BATCH):
        batch = todo[i:i + BATCH]
        response = access.openai_embedding(TIMEOUT, model=model, input=batch)
        data = response["data"] if isinstance(response, dict) else response.data
        vectors = [_vector(d) for d in data]
        with _cache() as c:
            c.executemany("INSERT OR REPLACE INTO vectors VALUES (?, ?)",
                          [(_key(model, t), array("f", v).tobytes()) for t, v in zip(batch, vectors)])
        have.update({_key(model, t): v for t, v in zip(batch, vectors)})
    return [have[k] for k in keys]


def cosine(a: list[float], b: list[float]) -> float:
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b)) / (na * nb) if na and nb else 0.0
