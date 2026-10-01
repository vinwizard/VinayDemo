"""Persistence and import: runs, companies and investigations as local JSON."""
import contextlib
import os
import re
import sqlite3
from pathlib import Path

from agents.ana import baseline_hash
from schemas import SCHEMA_VERSION, Company, Investigation, Run

BUNDLED = Path(__file__).resolve().parent / "data"
# DATA_DIR moves runs, companies and the access database onto a persistent disk (WEB.md, "Deploy to Render").
DATA = Path(os.environ.get("DATA_DIR") or BUNDLED)
RUNS = DATA / "runs"
COMPANIES = DATA / "companies"
INVESTIGATIONS = DATA / "investigations"   # the why agent's experiments (why.py), one file each
FLEETS = DATA / "fleets"                   # each investigation fleet's event log (fleet.py), one JSONL file each
ID = re.compile(r"[0-9a-f]{6,32}")


@contextlib.contextmanager
def sqlite(path: Path, schema: str):
    """The SQLite file at `path`, its tables made if missing; one transaction, committed on success."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    try:
        with conn:
            conn.executescript(schema)
            yield conn
    finally:
        conn.close()

def to_json(run: Run) -> str:
    return run.model_dump_json(indent=2)


def from_json(text: str) -> Run:
    run = Run.model_validate_json(text)
    if run.schema_version != SCHEMA_VERSION:
        raise ValueError(f"unsupported schema_version {run.schema_version}")
    frozen = sorted([*run.probes, *run.sampler.unasked], key=lambda p: p.id) if run.sampler else run.probes
    if run.baseline_hash and baseline_hash(frozen) != run.baseline_hash:
        raise ValueError("baseline questions do not match the recorded baseline hash")
    return run


def save_run(run: Run) -> Path:
    RUNS.mkdir(parents=True, exist_ok=True)
    path = RUNS / f"{run.id}.json"
    path.write_text(to_json(run))
    return path


def load_run(run_id: str) -> Run:
    if not ID.fullmatch(run_id):
        raise ValueError("bad run id")
    return from_json((RUNS / f"{run_id}.json").read_text())


# Onboarded companies, stored exactly like runs: local JSON, no database. Same durability caveat —
# see WEB.md "Deploy to Render": a container filesystem is ephemeral, so these survive a redeploy only under a
# DATA_DIR on a persistent disk.
def save_company(company: Company) -> Path:
    COMPANIES.mkdir(parents=True, exist_ok=True)
    path = COMPANIES / f"{company.id}.json"
    path.write_text(company.model_dump_json(indent=2))
    return path


def save_investigation(inv: Investigation) -> Path:
    INVESTIGATIONS.mkdir(parents=True, exist_ok=True)
    path = INVESTIGATIONS / f"{inv.id}.json"
    path.write_text(inv.model_dump_json(indent=2))
    return path


def load_investigation(inv_id: str) -> Investigation:
    if not ID.fullmatch(inv_id):
        raise ValueError("bad investigation id")
    return Investigation.model_validate_json((INVESTIGATIONS / f"{inv_id}.json").read_text())


def list_investigations(run_id: str) -> list[Investigation]:
    """A run's investigations, newest first."""
    out = []
    for path in INVESTIGATIONS.glob("*.json"):
        try:
            inv = Investigation.model_validate_json(path.read_text())
        except ValueError:
            continue
        if inv.run_id == run_id:
            out.append(inv)
    return sorted(out, key=lambda i: i.created_at, reverse=True)


def list_companies() -> list[Path]:
    return sorted(COMPANIES.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)


def load_company(company_id: str) -> Company:
    if not ID.fullmatch(company_id):
        raise ValueError("bad company id")
    company = Company.model_validate_json((COMPANIES / f"{company_id}.json").read_text())
    if company.schema_version != SCHEMA_VERSION:
        raise ValueError(f"unsupported schema_version {company.schema_version}")
    return company
