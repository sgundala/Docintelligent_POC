from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter

from meddoc.models import TemplateIngestRequest
from meddoc.storage import AUDIT, load_db

router = APIRouter()


@router.get("/api/package/completeness")
def package_completeness():
    import app as core

    db = load_db()
    return core.package_completeness_summary(db)


@router.get("/api/audit")
def get_audit(limit: int = 100):
    if not AUDIT.exists():
        return {"events": []}
    lines = AUDIT.read_text().strip().split("\n")
    events = []
    for line in lines[-limit:]:
        try:
            events.append(json.loads(line))
        except Exception:
            pass
    return {"events": list(reversed(events))}


@router.get("/api/schema")
def get_schema():
    import app as core

    db = load_db()
    return {
        "schema_registry": db["schema_registry"],
        "doc_types": list(core.DOC_TYPES.keys()),
        "template_count": len(db.get("templates", {})),
        "effective_doc_schemas": {dt: core.effective_schema(db, dt) for dt in core.DOC_TYPES.keys()},
        "section_taxonomy": core.SECTION_KEYWORDS,
    }


@router.get("/api/templates")
def list_templates():
    db = load_db()
    templates = sorted(db.get("templates", {}).values(), key=lambda x: x.get("ingested_at", ""), reverse=True)
    return {"templates": templates, "count": len(templates)}


@router.post("/api/templates/ingest")
def ingest_templates(body: Optional[TemplateIngestRequest] = None):
    import app as core

    filenames = body.filenames if body else None
    result = core.ingest_templates_into_ontology(filenames=filenames)
    return result

