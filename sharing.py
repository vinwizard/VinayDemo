"""Buyer answers shared across every brand tracked in one category.

A buyer question never names a brand, so the same question asked of the same model on the same day
is the same measurement whichever brand it is scored for: track a brand and five rivals in one
category and the buyer calls are paid once, not six times. Two things are kept, per category and
per UTC day (the day is part of the key, so nothing older is ever reused):

  pools    the buyer questions a front was planned with, so the next brand in the category asks
           the same ones (vetted again for that brand: one that names it is dropped, never reworded)
  answers  each fresh buyer answer, by (question, model, UTC day); a reuse is labelled `shared`
           and judged again for the brand it now scores — only the answer text is shared

Brand questions are never shared: they name the brand. Nothing here is a model call.
"""
import contextlib
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import reports
from schemas import Answer


def _day() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def default_path() -> Path:
    return reports.DATA / "shared.db"


class Store:
    def __init__(self, path: Optional[Path] = None):
        self.path = path or default_path()

    @contextlib.contextmanager
    def _db(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=10)
        try:
            with conn:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS pools (category TEXT NOT NULL, day TEXT NOT NULL,
                        questions TEXT NOT NULL, PRIMARY KEY (category, day));
                    CREATE TABLE IF NOT EXISTS answers (key TEXT PRIMARY KEY, day TEXT NOT NULL,
                        answer TEXT NOT NULL);
                """)
                yield conn
        finally:
            conn.close()

    def pool(self, category: str) -> list[str]:
        with self._db() as c:
            row = c.execute("SELECT questions FROM pools WHERE category = ? AND day = ?",
                            (_norm(category), _day())).fetchone()
        return json.loads(row[0]) if row else []

    def save_pool(self, category: str, questions: list[str]) -> None:
        if questions:
            with self._db() as c:
                c.execute("INSERT OR IGNORE INTO pools VALUES (?, ?, ?)",
                          (_norm(category), _day(), json.dumps(questions)))

    @staticmethod
    def _key(question: str, model: str) -> str:
        return hashlib.sha256(f"{_norm(question)}\0{model}\0{_day()}".encode()).hexdigest()

    def answer(self, question: str, model: str) -> Optional[Answer]:
        with self._db() as c:
            row = c.execute("SELECT answer FROM answers WHERE key = ?", (self._key(question, model),)).fetchone()
        return Answer.model_validate_json(row[0]) if row else None

    def save_answer(self, question: str, answer: Answer) -> None:
        """Only a grounded answer is worth sharing: an ungrounded one is excluded from every score."""
        if answer.status != "ok" or not answer.search_executed or answer.provenance != "live_api":
            return
        kept = answer.model_copy(update=dict(evaluator_labels=None, evaluator_model=None, probe_id="", try_no=1))
        with self._db() as c:
            c.execute("INSERT OR IGNORE INTO answers VALUES (?, ?, ?)",
                      (self._key(question, answer.model or ""), _day(), kept.model_dump_json()))
