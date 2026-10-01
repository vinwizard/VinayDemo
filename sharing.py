"""Questions and answers reused across runs: the one module that stores them.

  pools   the buyer questions a front was planned with, per category and UTC day, so the next brand
          in the category asks the same ones (vetted again for that brand: one that names it is
          dropped, never reworded)
  reuse   each fresh, grounded live answer of the last REUSE_HOURS, under its question, the mode it
          was asked in (model, search tool, reasoning effort) and the pass that paid for it; with the
          question's embedding for an unbranded buyer question. A later run asking the same question
          (`exact`), or a near-identical one (`near`, cosine >= the calibrated threshold), may reuse
          it: the answer text, citations and reading trace are kept, the labels are made again.

Which run may reuse what is the provider's (providers/live.LiveProvider.plan_reuse): within the pass
that paid for it, any question; another pass, only an unbranded buyer question the app wrote itself
(`open`), never one from the customer's own text or documents. With no pass set it is one pass.
Nothing here is a model call.

Upgrade path: this is SQLite on the one instance's disk (DATA_DIR), and the similarity search reads
every vector of the mode's last day in-process — fine for thousands of rows. Running several
instances would need a shared store (Postgres with pgvector, say) behind these same four methods.
"""
import contextlib
import json
import sqlite3
import time
from array import array
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple, Optional

import access
import embeddings
import reports
from schemas import Answer

REUSE_HOURS = 24
# Cosine between two questions' text-embedding-3-small vectors at or above which one's answer is
# reused for the other. Calibrated on 2026-10-01 (WEB.md "Answer reuse"): 12 saved buyer questions
# asked twice named the same companies at a Jaccard of 0.55; a trivial rewording (cosine 0.82-0.99)
# at 0.61, a free rewording of the same need (0.62-0.90) at 0.27, a related but different need
# (0.54-0.83) at 0.07. Pairs at 0.90 or above matched at 0.57 with 4.5% sharing no company (8% for
# the same question twice): reuse there is as safe as asking again. Below it the rewordings start.
SIMILARITY = 0.90
# The most of a run's first asks that may be reused, so every run still samples fresh answers.
MAX_SHARE = 0.5


def _day() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def _scope(text: str) -> str:
    return f"{access.SPENDER.get() or ''}\0{_norm(text)}"


class Hit(NamedTuple):
    id: int
    answer: Answer
    question: str          # the question it was asked for, as asked
    similarity: Optional[float]   # None for the same question


def default_path() -> Path:
    return reports.DATA / "shared.db"


class Store:
    def __init__(self, path: Optional[Path] = None):
        self.path = path or default_path()

    @contextlib.contextmanager
    def _db(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")   # runs read while others write
        try:
            with conn:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS pools (category TEXT NOT NULL, day TEXT NOT NULL,
                        questions TEXT NOT NULL, PRIMARY KEY (category, day));
                    CREATE TABLE IF NOT EXISTS reuse (id INTEGER PRIMARY KEY, pass TEXT NOT NULL,
                        mode TEXT NOT NULL, question TEXT NOT NULL, asked TEXT NOT NULL,
                        open INTEGER NOT NULL, origin TEXT NOT NULL, at REAL NOT NULL,
                        answer TEXT NOT NULL, vec BLOB);
                    CREATE INDEX IF NOT EXISTS reuse_exact ON reuse (mode, question, at);
                    CREATE INDEX IF NOT EXISTS reuse_near ON reuse (mode, at) WHERE vec IS NOT NULL;
                """)
                yield conn
        finally:
            conn.close()

    def pool(self, category: str) -> list[str]:
        with self._db() as c:
            row = c.execute("SELECT questions FROM pools WHERE category = ? AND day = ?",
                            (_scope(category), _day())).fetchone()
        return json.loads(row[0]) if row else []

    def save_pool(self, category: str, questions: list[str]) -> None:
        if questions:
            with self._db() as c:
                c.execute("INSERT OR IGNORE INTO pools VALUES (?, ?, ?)",
                          (_scope(category), _day(), json.dumps(questions)))

    def save(self, question: str, answer: Answer, mode: str, origin: str, open: bool = False,
             vec: Optional[list[float]] = None) -> None:
        """Only a fresh grounded live answer is kept: an ungrounded one is excluded from every score,
        and a reused one is not a new measurement."""
        if answer.status != "ok" or not answer.search_executed or answer.provenance != "live_api" or answer.shared:
            return
        kept = answer.model_copy(update=dict(evaluator_labels=None, evaluator_model=None, probe_id="", try_no=1))
        now = time.time()
        with self._db() as c:
            c.execute("DELETE FROM reuse WHERE at < ?", (now - REUSE_HOURS * 3600,))
            c.execute("INSERT INTO reuse (pass, mode, question, asked, open, origin, at, answer, vec) "
                      "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                      (access.SPENDER.get() or "", mode, _norm(question), question, int(open), origin, now,
                       kept.model_dump_json(), array("f", vec).tobytes() if vec else None))

    def _rows(self, where: str, args: tuple, origin: str, skip: set) -> list:
        """Rows of the last REUSE_HOURS this pass may read (its own, or open ones), not this run's own
        (`origin`) and not one this run reused already (`skip`), newest first."""
        with self._db() as c:
            rows = c.execute(f"SELECT id, asked, answer, vec FROM reuse WHERE {where} AND at >= ? "
                             "AND (pass = ? OR open = 1) AND origin != ? ORDER BY at DESC",
                             (*args, time.time() - REUSE_HOURS * 3600, access.SPENDER.get() or "", origin)
                             ).fetchall()
        return [r for r in rows if r[0] not in skip]

    def exact(self, question: str, mode: str, origin: str, skip: set) -> Optional[Hit]:
        rows = self._rows("mode = ? AND question = ?", (mode, _norm(question)), origin, skip)
        return Hit(rows[0][0], Answer.model_validate_json(rows[0][2]), rows[0][1], None) if rows else None

    def near(self, vec: list[float], mode: str, origin: str, skip: set, threshold: float) -> Optional[Hit]:
        """The most similar stored question at or above `threshold`, ties to the newest."""
        best = None
        for rid, asked, answer, blob in self._rows("mode = ? AND vec IS NOT NULL", (mode,), origin, skip):
            sim = embeddings.cosine(vec, array("f", blob).tolist())
            if sim >= threshold and (best is None or sim > best[3]):
                best = (rid, answer, asked, sim)
        return Hit(best[0], Answer.model_validate_json(best[1]), best[2], best[3]) if best else None
