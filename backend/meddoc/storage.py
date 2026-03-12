from __future__ import annotations

import datetime
import json
from pathlib import Path

# ── paths ─────────────────────────────────────────────────────────────────────
BASE = Path(__file__).resolve().parents[1]
UPLOADS = BASE / "uploads"
OUTPUTS = BASE / "outputs"
LOGS = BASE / "logs"
ONTOLOGY_DIR = BASE / "ontology_data"
DB_PATH = ONTOLOGY_DIR / "ontology_db.json"
AUDIT = LOGS / "audit.jsonl"
SAMPLE_DOCS = BASE / "sample_docs"
OUTPUTDOCS = BASE / "outputdocs"

for p in (UPLOADS, OUTPUTS, LOGS, ONTOLOGY_DIR, SAMPLE_DOCS):
    p.mkdir(exist_ok=True)


EMPTY_DB = {
    "version": 1,
    "documents": {},
    "elements": {},
    "relationships": [],
    "schema_registry": {},
    "templates": {},
}


def ensure_db_shape(db: dict) -> dict:
    db.setdefault("version", 1)
    db.setdefault("documents", {})
    db.setdefault("elements", {})
    db.setdefault("relationships", [])
    db.setdefault("schema_registry", {})
    db.setdefault("templates", {})
    return db


def load_db() -> dict:
    if DB_PATH.exists():
        return ensure_db_shape(json.loads(DB_PATH.read_text()))
    return ensure_db_shape(json.loads(json.dumps(EMPTY_DB)))


def save_db(db: dict):
    DB_PATH.write_text(json.dumps(db, indent=2, default=str))


def audit(event: str, payload: dict):
    entry = {"ts": datetime.datetime.utcnow().isoformat(), "event": event, **payload}
    with open(AUDIT, "a") as f:
        f.write(json.dumps(entry) + "\n")

