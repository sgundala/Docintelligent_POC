"""
MedDoc Intake POC — Backend (FastAPI + Groq)
============================================
Architecture decisions:
- Ontology stored as a self-evolving JSON graph (nodes + edges).
  New uploads ADD new node types/fields; nothing is deleted or rewritten.
- SHA-256 content hash used for dedup: re-uploading same file is a no-op.
- Groq (llama-3.3-70b-versatile) drives extraction + suggestions.
  Falls back to heuristic regex if GROQ_API_KEY is missing.
- All key events are appended to logs/audit.jsonl (one JSON per line).
"""

import os, json, uuid, hashlib, datetime, re, textwrap
from pathlib import Path
from typing import Optional, Dict, List, Set

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from meddoc.schemas import (
    DOC_TYPES as SCHEMA_DOC_TYPES,
    SECTION_KEYWORDS as SCHEMA_SECTION_KEYWORDS,
    SECTION_FIELD_HINTS as SCHEMA_SECTION_FIELD_HINTS,
)
from meddoc.pipeline import section_aware_extract_rag

try:
    import pdfplumber
    PDF_OK = True
except ImportError:
    PDF_OK = False

try:
    from docx import Document as DocxDoc
    DOCX_OK = True
except ImportError:
    DOCX_OK = False

try:
    from groq import Groq
    GROQ_OK = True
except ImportError:
    GROQ_OK = False

# ── paths ─────────────────────────────────────────────────────────────────────
BASE    = Path(__file__).parent
UPLOADS = BASE / "uploads";  UPLOADS.mkdir(exist_ok=True)
OUTPUTS = BASE / "outputs";  OUTPUTS.mkdir(exist_ok=True)
LOGS    = BASE / "logs";     LOGS.mkdir(exist_ok=True)
ONTOLOGY_DIR = BASE / "ontology_data"; ONTOLOGY_DIR.mkdir(exist_ok=True)
DB_PATH = ONTOLOGY_DIR / "ontology_db.json"
AUDIT   = LOGS / "audit.jsonl"
SAMPLE_DOCS = BASE / "sample_docs"; SAMPLE_DOCS.mkdir(exist_ok=True)
OUTPUTDOCS = BASE / "outputdocs"

# ── ontology DB ───────────────────────────────────────────────────────────────
EMPTY_DB = {
    "version": 1,
    "documents": {},
    "elements": {},
    "relationships": [],
    "schema_registry": {},
    "templates": {}
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

# ── document type schemas ─────────────────────────────────────────────────────
DOC_TYPES = {
    "clinical_evaluation_protocol": {
        "label": "Clinical Evaluation Protocol",
        "required_fields": [
            "document_title","document_number","version","date",
            "device_name","device_model","intended_purpose",
            "manufacturer_name","regulatory_framework",
            "evaluation_scope","literature_search_strategy",
            "inclusion_criteria","exclusion_criteria",
            "clinical_data_sources","equivalence_device",
            "benefit_risk_assessment","conclusions","author","reviewer"
        ],
        "optional_fields": [
            "device_classification","predicate_device",
            "post_market_surveillance_ref","notified_body","approval_date"
        ]
    },
    "risk_management_report": {
        "label": "Risk Management Report",
        "required_fields": [
            "document_title","document_number","version","date",
            "device_name","manufacturer_name","risk_management_standard",
            "hazard_identification","risk_estimation","risk_evaluation",
            "risk_control_measures","residual_risk_assessment",
            "benefit_risk_ratio","author","reviewer"
        ],
        "optional_fields": ["fmea_reference","fault_tree_ref"]
    },
    "test_protocol": {
        "label": "Test Protocol / Study Design",
        "required_fields": [
            "document_title","document_number","version","date",
            "test_objective","device_name","test_standard",
            "sample_size","acceptance_criteria","test_environment",
            "test_procedure","pass_fail_criteria","author","reviewer"
        ],
        "optional_fields": ["statistical_method","deviation_procedure"]
    },
    "design_history_file": {
        "label": "Design History File Entry",
        "required_fields": [
            "document_title","document_number","version","date",
            "device_name","design_input","design_output",
            "design_verification","design_validation",
            "design_review_record","author"
        ],
        "optional_fields": ["change_control_ref","risk_ref"]
    },
    "unknown": {
        "label": "Unknown Document",
        "required_fields": ["document_title","document_number","version","date"],
        "optional_fields": []
    }
}
DOC_TYPES = SCHEMA_DOC_TYPES

SECTION_KEYWORDS = {
    "document_control": ["document", "title", "version", "revision", "author", "reviewer", "approval", "metadata", "header"],
    "device_information": ["device", "product", "manufacturer", "model", "description", "classification"],
    "regulatory_framework": ["regulatory", "framework", "standard", "compliance", "iso", "mdr", "fda"],
    "evaluation_scope": ["scope", "objective", "purpose", "intended", "evaluation"],
    "evidence_methodology": ["literature", "search", "method", "criteria", "clinical data", "sources", "dataset"],
    "risk_assessment": ["risk", "hazard", "fmea", "control", "residual", "benefit"],
    "conclusion": ["conclusion", "summary", "decision", "recommendation"],
    "other": []
}
SECTION_KEYWORDS = SCHEMA_SECTION_KEYWORDS

SECTION_FIELD_HINTS = {
    "document_control": {"document_title", "document_number", "version", "date", "author", "reviewer"},
    "device_information": {"device_name", "device_model", "manufacturer_name", "device_classification", "predicate_device"},
    "regulatory_framework": {"regulatory_framework", "risk_management_standard", "notified_body", "approval_date"},
    "evaluation_scope": {"intended_purpose", "evaluation_scope", "test_objective", "test_environment"},
    "evidence_methodology": {
        "literature_search_strategy", "inclusion_criteria", "exclusion_criteria", "clinical_data_sources",
        "sample_size", "test_standard", "acceptance_criteria", "test_procedure", "pass_fail_criteria"
    },
    "risk_assessment": {
        "hazard_identification", "risk_estimation", "risk_evaluation", "risk_control_measures",
        "residual_risk_assessment", "benefit_risk_assessment", "benefit_risk_ratio"
    },
    "conclusion": {"conclusions"},
}
SECTION_FIELD_HINTS = SCHEMA_SECTION_FIELD_HINTS

def normalize_heading(line: str) -> str:
    out = re.sub(r"^\s*\d+(?:\.\d+)*[\)\.]?\s*", "", line.strip())
    return out.strip(":- ").strip()

def looks_like_heading(line: str) -> bool:
    s = line.strip()
    if len(s) < 4 or len(s) > 120:
        return False
    if ":" in s and not s.endswith(":"):
        return False
    if re.match(r"^\d+(?:\.\d+)*[\)\.]?\s+[A-Z][A-Z0-9 \-_/&]{2,}$", s):
        return True
    if re.match(r"^[A-Z][A-Z0-9 \-_/&]{4,}$", s):
        return True
    if re.match(r"^[A-Z][A-Za-z0-9 \-_/&]{4,}:$", s):
        return True
    return False

def classify_section_key(heading: str) -> str:
    h = heading.lower()
    best = ("other", 0)
    for key, tokens in SECTION_KEYWORDS.items():
        score = sum(1 for t in tokens if t in h)
        if score > best[1]:
            best = (key, score)
    return best[0]

def extract_sections(text: str) -> List[Dict[str, str]]:
    lines = text.splitlines()
    sections: List[Dict[str, str]] = []
    current = {"heading": "Preamble", "section_key": "document_control", "lines": []}
    for raw in lines:
        line = raw.rstrip("\n")
        if looks_like_heading(line):
            if current["lines"]:
                body = "\n".join(current["lines"]).strip()
                if body:
                    sections.append({
                        "heading": current["heading"],
                        "section_key": current["section_key"],
                        "text": body
                    })
            heading = normalize_heading(line)
            current = {"heading": heading or "Untitled", "section_key": classify_section_key(heading), "lines": []}
            continue
        current["lines"].append(line)
    if current["lines"]:
        body = "\n".join(current["lines"]).strip()
        if body:
            sections.append({
                "heading": current["heading"],
                "section_key": current["section_key"],
                "text": body
            })
    return sections[:40]

# ── Groq client ───────────────────────────────────────────────────────────────
def get_groq():
    key = os.environ.get("GROQ_API_KEY","")
    if GROQ_OK and key:
        return Groq(api_key=key)
    return None

def groq_complete(prompt: str, system: str = "", max_tokens: int = 2048) -> str:
    client = get_groq()
    if not client:
        return ""
    msgs = []
    if system:
        msgs.append({"role":"system","content":system})
    msgs.append({"role":"user","content":prompt})
    try:
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=msgs, max_tokens=max_tokens, temperature=0.1
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        # Fail open to heuristic path (e.g., Groq rate limit / transient error).
        audit("groq_request_error", {"error": str(e)[:400]})
        return ""

# ── text extraction ───────────────────────────────────────────────────────────
def extract_text(path: Path, mime: str) -> str:
    if mime == "application/pdf" and PDF_OK:
        with pdfplumber.open(path) as pdf:
            return "\n".join(p.extract_text() or "" for p in pdf.pages)
    if "wordprocessingml" in mime and DOCX_OK:
        doc = DocxDoc(str(path))
        return "\n".join(p.text for p in doc.paragraphs)
    try:
        return path.read_text(errors="replace")
    except:
        return ""

def normalize_field_name(label: str) -> str:
    label = label.strip().lower()
    label = re.sub(r"\(.*?\)", " ", label)
    label = re.sub(r"[^a-z0-9]+", "_", label)
    label = re.sub(r"_+", "_", label).strip("_")
    if not label or len(label) < 3:
        return ""
    return label

def extract_template_fields(text: str) -> List[str]:
    candidates: Set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or len(line) > 160:
            continue

        # Label-like forms commonly used in templates.
        m_colon = re.match(r"^([A-Za-z][A-Za-z0-9 \/\-\(\)]{2,90})\s*:\s*$", line)
        m_blank = re.match(r"^([A-Za-z][A-Za-z0-9 \/\-\(\)]{2,90})\s*[_\.]{3,}\s*$", line)
        m_field = re.match(r"^(?:field|item)\s*[:\-]\s*([A-Za-z][A-Za-z0-9 \/\-\(\)]{2,90})$", line, re.IGNORECASE)

        label = None
        if m_colon:
            label = m_colon.group(1)
        elif m_blank:
            label = m_blank.group(1)
        elif m_field:
            label = m_field.group(1)

        if label:
            key = normalize_field_name(label)
            if key:
                candidates.add(key)

    # Also capture inline key:value style labels, usually metadata headers.
    for m in re.finditer(r"([A-Za-z][A-Za-z0-9 \/\-\(\)]{2,40})\s*:\s*[^\n]{0,80}", text):
        key = normalize_field_name(m.group(1))
        if key:
            candidates.add(key)

    return sorted(candidates)

def upsert_schema_field_from_template(db: dict, field_name: str, doc_type: str, template_id: str):
    reg = db["schema_registry"].setdefault(
        field_name,
        {"type":"string","docs_seen_in":[],"required_in":[],"template_seen_in":[],"template_doc_types":[]}
    )
    reg.setdefault("docs_seen_in", [])
    reg.setdefault("required_in", [])
    reg.setdefault("template_seen_in", [])
    reg.setdefault("template_doc_types", [])
    if template_id not in reg["template_seen_in"]:
        reg["template_seen_in"].append(template_id)
    if doc_type != "unknown" and doc_type not in reg["template_doc_types"]:
        reg["template_doc_types"].append(doc_type)

def template_fields_for_doc_type(db: dict, doc_type: str) -> List[str]:
    fields = []
    for field_name, reg in db.get("schema_registry", {}).items():
        if not isinstance(reg, dict):
            continue
        # Prefer explicit template_doc_types; keep legacy compatibility with prior data
        tdocs = reg.get("template_doc_types", [])
        legacy_required = reg.get("required_in", [])
        has_template_refs = bool(reg.get("template_seen_in"))
        if doc_type in tdocs or (has_template_refs and doc_type in legacy_required):
            fields.append(field_name)
    return sorted(set(fields))

def effective_schema(db: dict, doc_type: str) -> Dict[str, List[str] | str]:
    base = DOC_TYPES.get(doc_type, DOC_TYPES["unknown"])
    req = list(base["required_fields"])
    opt = list(base["optional_fields"])
    tmpl = [f for f in template_fields_for_doc_type(db, doc_type) if f not in req and f not in opt]
    return {
        "label": base["label"],
        "required_fields": req,
        "optional_fields": opt + tmpl,
        "template_fields": tmpl
    }

def ingest_templates_into_ontology(filenames: Optional[List[str]] = None) -> dict:
    db = load_db()
    allowed = {".pdf": "application/pdf", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".txt": "text/plain"}
    files = []
    sources = [SAMPLE_DOCS]
    if OUTPUTDOCS.exists():
        sources.append(OUTPUTDOCS)
    for src in sources:
        for p in sorted(src.iterdir()):
            if not p.is_file():
                continue
            if p.suffix.lower() not in allowed:
                continue
            if filenames and p.name not in filenames:
                continue
            files.append(p)

    ingested = []
    deduplicated = []
    skipped = []
    for p in files:
        raw = p.read_bytes()
        sha256 = hashlib.sha256(raw).hexdigest()
        existing = None
        for tid, node in db["templates"].items():
            if node.get("sha256") == sha256:
                existing = (tid, node)
                break
        if existing:
            deduplicated.append({"filename": p.name, "template_id": existing[0]})
            continue

        mime = allowed[p.suffix.lower()]
        text = extract_text(p, mime)
        if not text.strip():
            skipped.append({"filename": p.name, "reason": "no_text_extracted"})
            continue
        doc_type = detect_doc_type(text, p.name)
        fields = extract_template_fields(text)
        template_id = str(uuid.uuid4())
        node = {
            "template_id": template_id,
            "filename": p.name,
            "sha256": sha256,
            "doc_type": doc_type,
            "text_length": len(text),
            "field_count": len(fields),
            "fields": fields,
            "ingested_at": datetime.datetime.utcnow().isoformat()
        }
        db["templates"][template_id] = node
        for f in fields:
            upsert_schema_field_from_template(db, f, doc_type, template_id)
            db["relationships"].append({"from": template_id, "to": f, "type": "template_defines_field"})
        ingested.append({"filename": p.name, "template_id": template_id, "doc_type": doc_type, "field_count": len(fields)})
        audit("template_ingested", {"template_id": template_id, "filename": p.name, "doc_type": doc_type, "field_count": len(fields)})

    save_db(db)
    return {
        "processed_count": len(files),
        "ingested_count": len(ingested),
        "deduplicated_count": len(deduplicated),
        "skipped_count": len(skipped),
        "ingested": ingested,
        "deduplicated": deduplicated,
        "skipped": skipped
    }

def required_output_doc_types(db: dict) -> List[str]:
    # Prefer template-derived required output set when available.
    templ_types = sorted({
        t.get("doc_type") for t in db.get("templates", {}).values()
        if t.get("doc_type") and t.get("doc_type") != "unknown"
    })
    if templ_types:
        return templ_types
    return [t for t in DOC_TYPES.keys() if t != "unknown"]

def package_completeness_summary(db: dict) -> dict:
    docs = list(db["documents"].values())
    avg_field_completeness = round(sum(d["completeness"]["completeness_pct"] for d in docs)/len(docs),1) if docs else 0.0
    required_types = required_output_doc_types(db)
    present_types = sorted({d.get("doc_type") for d in docs if d.get("doc_type") in required_types})
    missing_types = [t for t in required_types if t not in present_types]
    output_doc_coverage_pct = round((len(present_types)/len(required_types))*100,1) if required_types else 100.0

    # Per-output-template completeness matrix.
    doc_elements: Dict[str, Dict[str, str]] = {}
    for e in db.get("elements", {}).values():
        doc_id = e.get("doc_id")
        field = e.get("field")
        if not doc_id or not field:
            continue
        val = str(e.get("value", "")).strip()
        if not val:
            continue
        doc_elements.setdefault(doc_id, {})
        doc_elements[doc_id][field] = val

    matrix = []
    templates = sorted(db.get("templates", {}).values(), key=lambda t: (t.get("doc_type", ""), t.get("filename", "")))
    for t in templates:
        doc_type = t.get("doc_type") or "unknown"
        schema_req = list(effective_schema(db, doc_type).get("required_fields", []))
        template_fields = sorted(set(t.get("fields", []) or []))
        t_fields = schema_req if doc_type != "unknown" and schema_req else template_fields
        if not t_fields:
            continue
        candidates = [d for d in docs if d.get("doc_type") == doc_type]
        best_doc = None
        best_present: List[str] = []
        for d in candidates:
            present = [f for f in t_fields if doc_elements.get(d["doc_id"], {}).get(f)]
            if len(present) > len(best_present):
                best_present = present
                best_doc = d
        missing = [f for f in t_fields if f not in best_present]
        pct = round((len(best_present) / len(t_fields)) * 100, 1) if t_fields else 100.0
        matrix.append({
            "template_id": t.get("template_id"),
            "filename": t.get("filename"),
            "doc_type": doc_type,
            "required_total": len(t_fields),
            "required_present": len(best_present),
            "completeness_pct": pct,
            "missing_fields": missing,
            "matched_doc_id": best_doc.get("doc_id") if best_doc else None,
            "matched_doc_filename": best_doc.get("filename") if best_doc else None,
            "matched_doc_uploaded_at": best_doc.get("uploaded_at") if best_doc else None,
            "scoring_basis": "doc_type_required_fields" if doc_type != "unknown" and schema_req else "template_fields",
        })

    if not matrix:
        # Fallback matrix using base schemas when no templates exist.
        for dt in required_types:
            schema = effective_schema(db, dt)
            req_fields = schema.get("required_fields", [])
            candidates = [d for d in docs if d.get("doc_type") == dt]
            best_doc = None
            best_present: List[str] = []
            for d in candidates:
                present = [f for f in req_fields if doc_elements.get(d["doc_id"], {}).get(f)]
                if len(present) > len(best_present):
                    best_present = present
                    best_doc = d
            missing = [f for f in req_fields if f not in best_present]
            pct = round((len(best_present) / len(req_fields)) * 100, 1) if req_fields else 100.0
            matrix.append({
                "template_id": None,
                "filename": DOC_TYPES.get(dt, {}).get("label", dt),
                "doc_type": dt,
                "required_total": len(req_fields),
                "required_present": len(best_present),
                "completeness_pct": pct,
                "missing_fields": missing,
                "matched_doc_id": best_doc.get("doc_id") if best_doc else None,
                "matched_doc_filename": best_doc.get("filename") if best_doc else None,
                "matched_doc_uploaded_at": best_doc.get("uploaded_at") if best_doc else None,
            })

    matrix_avg = round(sum(m["completeness_pct"] for m in matrix) / len(matrix), 1) if matrix else 0.0
    return {
        "required_output_doc_types": required_types,
        "present_output_doc_types": present_types,
        "missing_output_doc_types": missing_types,
        "required_output_total": len(required_types),
        "present_output_total": len(present_types),
        "output_doc_coverage_pct": output_doc_coverage_pct,
        "avg_document_field_completeness_pct": avg_field_completeness,
        "output_template_matrix": matrix,
        "output_template_matrix_avg_pct": matrix_avg,
    }

def primary_template_for_doc_type(db: dict, doc_type: str) -> Optional[dict]:
    candidates = [t for t in db.get("templates", {}).values() if t.get("doc_type") == doc_type]
    if not candidates:
        return None
    candidates.sort(key=lambda t: (t.get("field_count", 0), t.get("ingested_at", "")), reverse=True)
    return candidates[0]

# ── doc type detection ────────────────────────────────────────────────────────
def detect_doc_type(text: str, filename: str) -> str:
    tl = (text + filename).lower()
    scores = {
        "clinical_evaluation_protocol": sum(1 for k in [
            "clinical evaluation","literature search","equivalen",
            "clinical data","benefit.*risk","mdr","mdcg"
        ] if re.search(k,tl)),
        "risk_management_report": sum(1 for k in [
            "risk management","iso 14971","hazard","fmea","residual risk"
        ] if re.search(k,tl)),
        "test_protocol": sum(1 for k in [
            "test protocol","test procedure","acceptance criteria",
            "sample size","pass.*fail","test standard"
        ] if re.search(k,tl)),
        "design_history_file": sum(1 for k in [
            "design history","design input","design output",
            "design verification","dhf"
        ] if re.search(k,tl)),
    }
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] > 0 else "unknown"

# ── heuristic extraction ──────────────────────────────────────────────────────
def heuristic_extract(text: str, doc_type: str, field_filter: Optional[Set[str]] = None, source: str = "heuristic_regex", section: str = "Document-wide") -> Dict[str,Dict]:
    fields = {}
    patterns = {
        "document_title":    r"(?:title|document title)[:\s]+([^\n]{5,120})",
        "document_number":   r"(?:doc(?:ument)?\s*(?:no|number|#|id))[:\s#]+([A-Z0-9\-\/]{3,40})",
        "version":           r"(?:version|rev(?:ision)?)[:\s]+([0-9A-Za-z\.]{1,20})",
        "date":              r"(?:date)[:\s]+(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4}|\w+ \d{1,2},? \d{4}|\d{4}-\d{2}-\d{2})",
        "device_name":       r"(?:device name|product name)[:\s]+([^\n]{3,80})",
        "device_model":      r"(?:model(?:\s*no)?)[:\s]+([^\n]{2,60})",
        "manufacturer_name": r"(?:manufacturer|company)[:\s]+([^\n]{3,80})",
        "author":            r"(?:author|prepared by|written by)[:\s]+([^\n]{3,80})",
        "reviewer":          r"(?:reviewer|reviewed by|approved by)[:\s]+([^\n]{3,80})",
        "intended_purpose":  r"(?:intended purpose|intended use)[:\s]+([^\n]{10,300})",
        "regulatory_framework": r"(MDR 2017/745|IVDR 2017/746|FDA 21 CFR|ISO 13485|ISO 14155)",
        "evaluation_scope":  r"(?:scope|evaluation scope)[:\s]+([^\n]{10,300})",
        "risk_management_standard": r"(ISO 14971:\d{4})",
        "test_standard":     r"(?:standard|test standard)[:\s]+([^\n]{3,80})",
        "acceptance_criteria": r"(?:acceptance criteria)[:\s]+([^\n]{5,200})",
        "sample_size":       r"(?:sample size)[:\s]+(\d+[^\n]{0,50})",
        "literature_search_strategy": r"(?:literature search|search strategy)[:\s]+([^\n]{10,300})",
        "inclusion_criteria": r"(?:inclusion criteria?|inclusion)[:\s]+([^\n]{10,300})",
        "exclusion_criteria": r"(?:exclusion criteria?|exclusion)[:\s]+([^\n]{10,300})",
        "clinical_data_sources": r"(?:clinical data sources?|data sources?)[:\s]+([^\n]{10,300})",
        "biocompatibility_standard": r"(ISO\s*10993(?:\-\d+)?)",
        "biological_endpoints_evaluated": r"(?:biological endpoints evaluated|endpoints evaluated)[:\s]+([^\n]{8,300})",
        "biocompatibility_assessment": r"(?:biocompatibility (?:assessment|evaluation|summary))[:\s]+([^\n]{10,400})",
        "cytotoxicity_result": r"(?:cytotoxicity(?:\s*test)?(?:\s*result)?|in vitro cytotoxicity)[:\s]+([^\n]{5,300})",
        "sensitization_result": r"(?:sensitization(?:\s*test)?(?:\s*result)?|skin sensitization)[:\s]+([^\n]{5,300})",
        "irritation_result": r"(?:irritation(?:\/intracutaneous reactivity)?(?:\s*test)?(?:\s*result)?)[:\s]+([^\n]{5,300})",
    }
    for field, pattern in patterns.items():
        if field_filter is not None and field not in field_filter:
            continue
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            val = m.group(1).strip()
            start = max(0, m.start()-60)
            end   = min(len(text), m.end()+60)
            evidence = text[start:end].replace("\n"," ").strip()
            fields[field] = {
                "value": val, "confidence": 0.7,
                "source": source, "evidence": evidence, "section": section
            }

    # Biocompatibility-specific pass for table/line style content (ISO 10993 lists).
    def extract_biocompatibility_structured(txt: str) -> Dict[str, Dict]:
        out: Dict[str, Dict] = {}
        if not re.search(r"biocompat|iso\s*10993|cytotoxic|sensitization|irritation", txt, re.IGNORECASE):
            return out

        lines = [ln.strip() for ln in txt.splitlines() if ln.strip()]
        joined = " ".join(lines)
        iso_hits = sorted(set(re.findall(r"ISO\s*10993(?:\-\d+)?", joined, re.IGNORECASE)))
        if iso_hits:
            val = ", ".join(iso_hits)
            out["biocompatibility_standard"] = {
                "value": val,
                "confidence": 0.9,
                "source": source,
                "evidence": val,
                "section": section
            }

        endpoint_map = {
            "cytotoxicity_result": (r"cytotoxic(?:ity)?", "Cytotoxicity"),
            "sensitization_result": (r"sensitization|skin sensitization", "Sensitization"),
            "irritation_result": (r"irritation|intracutaneous reactivity", "Irritation / Intracutaneous Reactivity"),
        }
        endpoints_found = []
        for field_name, (kw_pat, label) in endpoint_map.items():
            if re.search(kw_pat, joined, re.IGNORECASE):
                endpoints_found.append(label)
                # Prefer line-level evidence that includes endpoint + ISO tag.
                if field_name == "irritation_result":
                    line_hit = next(
                        (ln for ln in lines if re.search(r"intracutaneous reactivity", ln, re.IGNORECASE) and re.search(r"ISO\s*10993", ln, re.IGNORECASE)),
                        None
                    )
                    if not line_hit:
                        line_hit = next(
                            (ln for ln in lines if re.search(r"\birritation\b", ln, re.IGNORECASE) and re.search(r"ISO\s*10993", ln, re.IGNORECASE)),
                            None
                        )
                else:
                    line_hit = next(
                        (ln for ln in lines if re.search(kw_pat, ln, re.IGNORECASE) and re.search(r"ISO\s*10993", ln, re.IGNORECASE)),
                        None
                    )
                if not line_hit:
                    line_hit = next((ln for ln in lines if re.search(kw_pat, ln, re.IGNORECASE)), "")
                out[field_name] = {
                    "value": line_hit or label,
                    "confidence": 0.88,
                    "source": source,
                    "evidence": (line_hit or label)[:220],
                    "section": section
                }

        if endpoints_found:
            out["biological_endpoints_evaluated"] = {
                "value": ", ".join(endpoints_found),
                "confidence": 0.9,
                "source": source,
                "evidence": ", ".join(endpoints_found),
                "section": section
            }
            out["biocompatibility_assessment"] = {
                "value": f"Biocompatibility endpoints covered: {', '.join(endpoints_found)}.",
                "confidence": 0.82,
                "source": source,
                "evidence": ", ".join(endpoints_found),
                "section": section
            }
        return out

    structured = extract_biocompatibility_structured(text)
    for f, cand in structured.items():
        if field_filter is not None and f not in field_filter:
            continue
        cur = fields.get(f)
        if not cur:
            fields[f] = cand
            continue
        if len(str(cand.get("value", ""))) > len(str(cur.get("value", ""))):
            fields[f] = cand
    return fields

# ── Groq extraction ───────────────────────────────────────────────────────────
def groq_extract_fields(text: str, doc_type: str, fields: List[str], source: str = "groq_llm", section: str = "Document-wide") -> Dict[str,Dict]:
    if not fields:
        return {}
    db = load_db()
    schema = effective_schema(db, doc_type)
    truncated = text[:6000]
    system = textwrap.dedent("""
        You are a medical device regulatory document analyst.
        Extract structured fields from the document text.
        Return ONLY valid JSON — no markdown, no explanation.
        For each found field return:
        { "field_name": { "value": "...", "evidence": "exact quote up to 120 chars", "confidence": 0.0-1.0 } }
        Omit fields not found.
    """).strip()
    prompt = f"""Document type: {schema['label']}
Fields to extract: {json.dumps(fields)}
Document text:
---
{truncated}
---
JSON only."""
    raw = groq_complete(prompt, system=system, max_tokens=2000)
    try:
        raw = re.sub(r"```(?:json)?|```","",raw).strip()
        parsed = json.loads(raw)
        out = {}
        for k,v in parsed.items():
            if isinstance(v,dict) and "value" in v:
                out[k] = {
                    "value": str(v.get("value","")),
                    "confidence": float(v.get("confidence",0.85)),
                    "source": source,
                    "evidence": str(v.get("evidence",""))[:200],
                    "section": section
                }
        return out
    except Exception as e:
        audit("groq_parse_error",{"error":str(e),"raw":raw[:300]})
        return {}

def groq_extract(text: str, doc_type: str) -> Dict[str,Dict]:
    db = load_db()
    schema = effective_schema(db, doc_type)
    all_fields = schema["required_fields"] + schema["optional_fields"]
    return groq_extract_fields(text, doc_type, all_fields, source="groq_llm", section="Document-wide")

def merge_extracted_values(base: Dict[str, Dict], incoming: Dict[str, Dict]) -> Dict[str, Dict]:
    for field, cand in incoming.items():
        if field not in base:
            base[field] = cand
            continue
        current = base[field]
        cur_val = str(current.get("value", "")).strip()
        new_val = str(cand.get("value", "")).strip()
        if not cur_val and new_val:
            base[field] = cand
            continue
        if new_val and float(cand.get("confidence", 0.0)) > float(current.get("confidence", 0.0)):
            base[field] = cand
    return base

def section_aware_extract(text: str, doc_type: str) -> tuple[Dict[str,Dict], List[Dict[str, object]]]:
    db = load_db()
    schema = effective_schema(db, doc_type)
    all_fields = schema["required_fields"] + schema["optional_fields"]
    return section_aware_extract_rag(
        text=text,
        doc_type=doc_type,
        all_fields=all_fields,
        required_fields=schema["required_fields"],
        use_groq=bool(get_groq()),
        groq_extract_fields=groq_extract_fields,
        heuristic_extract=heuristic_extract,
    )

# ── suggestion generation ─────────────────────────────────────────────────────
HEURISTIC_DEFAULTS = {
    "regulatory_framework": "MDR 2017/745 (EU)",
    "risk_management_standard": "ISO 14971:2019",
    "version": "1.0",
    "evaluation_scope": "Full clinical evaluation per MEDDEV 2.7/1 rev 4",
    "literature_search_strategy": "Systematic search of PubMed, Embase, and manufacturer data",
    "benefit_risk_assessment": "Benefits outweigh residual risks based on available clinical evidence",
    "clinical_data_sources": "Published literature, post-market surveillance data, clinical investigations",
    "inclusion_criteria": "Peer-reviewed studies using the device or an equivalent device",
    "exclusion_criteria": "Case reports, animal studies, studies with fewer than 10 subjects",
    "conclusions": "Based on the clinical evidence reviewed, the device demonstrates acceptable safety and performance.",
    "reviewer": "Head of Regulatory Affairs",
}

def generate_suggestions(doc_id: str, doc_type: str, extracted: Dict[str,Dict], text: str) -> List[Dict]:
    db = load_db()
    schema = effective_schema(db, doc_type)
    missing = [f for f in schema["required_fields"] if f not in extracted]
    if not missing:
        return []
    suggestions = []
    client_available = bool(get_groq())
    if client_available and text:
        system = textwrap.dedent("""
            You are a medical device regulatory expert.
            For each missing field, propose a value based on context and regulatory best practices.
            Return ONLY valid JSON:
            { "field_name": { "suggested_value": "...", "rationale": "why, up to 150 chars" } }
            Omit fields you cannot suggest.
        """).strip()
        prompt = f"""Document type: {schema['label']}
Missing required fields: {json.dumps(missing)}
Already extracted: {json.dumps({k:v['value'] for k,v in extracted.items()})}
Document excerpt:
---
{text[:4000]}
---
JSON only."""
        raw = groq_complete(prompt, system=system, max_tokens=1500)
        try:
            raw = re.sub(r"```(?:json)?|```","",raw).strip()
            proposed = json.loads(raw)
            for field, data in proposed.items():
                if field in missing and isinstance(data,dict):
                    suggestions.append({
                        "id": str(uuid.uuid4()), "doc_id": doc_id, "field": field,
                        "suggested_value": str(data.get("suggested_value","")),
                        "rationale": str(data.get("rationale",""))[:200],
                        "source": "groq_suggestion", "status": "pending"
                    })
        except Exception as e:
            audit("suggestion_parse_error",{"error":str(e)})
    filled = {s["field"] for s in suggestions}
    for field in missing:
        if field not in filled and field in HEURISTIC_DEFAULTS:
            suggestions.append({
                "id": str(uuid.uuid4()), "doc_id": doc_id, "field": field,
                "suggested_value": HEURISTIC_DEFAULTS[field],
                "rationale": "Regulatory best-practice default for this document type",
                "source": "heuristic_default", "status": "pending"
            })
    return suggestions

# ── completeness ──────────────────────────────────────────────────────────────
def compute_completeness(doc_type: str, extracted: Dict) -> Dict:
    db = load_db()
    schema = effective_schema(db, doc_type)
    req = schema["required_fields"]
    opt = schema["optional_fields"]
    present_req = [f for f in req if f in extracted and str(extracted[f].get("value","")).strip()]
    present_opt = [f for f in opt if f in extracted and str(extracted[f].get("value","")).strip()]
    pct = round(len(present_req)/len(req)*100,1) if req else 100.0
    return {
        "required_total": len(req), "required_present": len(present_req),
        "optional_total": len(opt), "optional_present": len(present_opt),
        "completeness_pct": pct,
        "missing_required": [f for f in req if f not in present_req]
    }

def infer_field_relationship_pairs(doc_type: str) -> List[Dict[str, str]]:
    common = [
        {"from": "document_number", "to": "version", "type": "field_related", "reason": "document_identity"},
        {"from": "document_number", "to": "date", "type": "field_related", "reason": "document_identity"},
        {"from": "device_name", "to": "device_model", "type": "field_related", "reason": "device_identity"},
        {"from": "device_name", "to": "manufacturer_name", "type": "field_related", "reason": "device_identity"},
    ]
    doc_specific = {
        "clinical_evaluation_protocol": [
            {"from": "intended_purpose", "to": "evaluation_scope", "type": "field_related", "reason": "clinical_logic"},
            {"from": "clinical_data_sources", "to": "literature_search_strategy", "type": "field_related", "reason": "evidence_chain"},
            {"from": "benefit_risk_assessment", "to": "conclusions", "type": "field_related", "reason": "conclusion_basis"},
        ],
        "risk_management_report": [
            {"from": "hazard_identification", "to": "risk_estimation", "type": "field_related", "reason": "risk_flow"},
            {"from": "risk_estimation", "to": "risk_evaluation", "type": "field_related", "reason": "risk_flow"},
            {"from": "risk_evaluation", "to": "risk_control_measures", "type": "field_related", "reason": "risk_flow"},
            {"from": "risk_control_measures", "to": "residual_risk_assessment", "type": "field_related", "reason": "risk_flow"},
        ],
        "test_protocol": [
            {"from": "test_objective", "to": "test_procedure", "type": "field_related", "reason": "test_design"},
            {"from": "test_standard", "to": "acceptance_criteria", "type": "field_related", "reason": "test_design"},
            {"from": "acceptance_criteria", "to": "pass_fail_criteria", "type": "field_related", "reason": "test_design"},
        ],
        "design_history_file": [
            {"from": "design_input", "to": "design_output", "type": "field_related", "reason": "design_flow"},
            {"from": "design_output", "to": "design_verification", "type": "field_related", "reason": "design_flow"},
            {"from": "design_output", "to": "design_validation", "type": "field_related", "reason": "design_flow"},
        ],
    }
    return common + doc_specific.get(doc_type, [])

def rebuild_doc_element_relationships(db: dict, doc_id: str, doc_type: str):
    # Remove previous inferred relationships for this document.
    doc_elem_ids = {e["elem_id"] for e in db["elements"].values() if e.get("doc_id") == doc_id}
    db["relationships"] = [
        r for r in db["relationships"]
        if not (r.get("type") == "field_related" and r.get("from") in doc_elem_ids and r.get("to") in doc_elem_ids)
    ]

    field_to_elem = {e["field"]: e for e in db["elements"].values() if e.get("doc_id") == doc_id}
    for rel in infer_field_relationship_pairs(doc_type):
        a = field_to_elem.get(rel["from"])
        b = field_to_elem.get(rel["to"])
        if not a or not b:
            continue
        if not str(a.get("value", "")).strip() or not str(b.get("value", "")).strip():
            continue
        db["relationships"].append({
            "from": a["elem_id"], "to": b["elem_id"],
            "type": rel["type"], "reason": rel["reason"]
        })

def generate_output_lines(doc: dict, elements: Dict[str, dict], schema: dict, template: Optional[dict] = None) -> List[str]:
    def fv(f):
        e = elements.get(f)
        return e["value"] if e else "[NOT PROVIDED]"

    ts = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "="*80,
        f"  {schema['label'].upper()}",
        f"  Generated by MedDoc Intake POC  |  {ts}",
        "="*80,"",
        "DOCUMENT INFORMATION","--------------------",
        f"Title:           {fv('document_title')}",
        f"Document No.:    {fv('document_number')}",
        f"Version:         {fv('version')}",
        f"Date:            {fv('date')}",
        f"Author:          {fv('author')}",
        f"Reviewer:        {fv('reviewer')}","",
        "DEVICE INFORMATION","------------------",
        f"Device Name:     {fv('device_name')}",
        f"Device Model:    {fv('device_model')}",
        f"Manufacturer:    {fv('manufacturer_name')}","",
    ]
    if doc["doc_type"]=="clinical_evaluation_protocol":
        lines += [
            "REGULATORY FRAMEWORK","---------------------",fv('regulatory_framework'),"",
            "INTENDED PURPOSE","----------------",fv('intended_purpose'),"",
            "EVALUATION SCOPE","----------------",fv('evaluation_scope'),"",
            "LITERATURE SEARCH STRATEGY","--------------------------",fv('literature_search_strategy'),"",
            "INCLUSION CRITERIA","------------------",fv('inclusion_criteria'),"",
            "EXCLUSION CRITERIA","------------------",fv('exclusion_criteria'),"",
            "CLINICAL DATA SOURCES","---------------------",fv('clinical_data_sources'),"",
            "EQUIVALENCE DEVICE","------------------",fv('equivalence_device'),"",
            "BENEFIT-RISK ASSESSMENT","-----------------------",fv('benefit_risk_assessment'),"",
            "CONCLUSIONS","-----------",fv('conclusions'),"",
        ]
    lines += [
        "COMPLETENESS SUMMARY","--------------------",
        f"Required fields present: {doc['completeness']['required_present']}/{doc['completeness']['required_total']}",
        f"Completeness: {doc['completeness']['completeness_pct']}%",
        f"Missing: {', '.join(doc['completeness']['missing_required']) or 'None'}","",
        "TRACEABILITY","------------",
        f"Source document: {doc['filename']}",
        f"Ingested at:     {doc['uploaded_at']}",
        f"SHA-256:         {doc['sha256']}","",
        "FIELD AUDIT TRAIL","-----------------",
    ]
    for field in schema["required_fields"]+schema["optional_fields"]:
        e = elements.get(field)
        if e:
            ev = e['evidence'][:70].replace('\n',' ') if e.get('evidence') else "—"
            lines.append(f"  {field:<35} | src={e['source']:<22} | conf={int(e['confidence']*100)}% | ev: {ev}")
    if template and template.get("fields"):
        lines += ["", "TEMPLATE ALIGNMENT", "------------------"]
        lines.append(f"Template source: {template.get('filename','(unknown)')}")
        for f in template.get("fields", []):
            val = elements.get(f, {}).get("value", "[NOT PROVIDED]")
            lines.append(f"  {f:<35} | {val}")
    lines += ["","="*80,f"  END OF DOCUMENT  |  {ts}","="*80]
    return lines

def write_output_docx(doc_id: str, doc: dict, elements: Dict[str, dict], schema: dict, template: Optional[dict] = None) -> Path:
    out_path = OUTPUTS / f"{doc_id}_output.docx"
    d = DocxDoc()
    d.add_heading(schema["label"], level=1)
    d.add_paragraph(f"Generated by MedDoc Intake POC")
    d.add_paragraph(f"Timestamp: {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")

    def add_kv(title: str, field: str):
        val = elements.get(field, {}).get("value", "[NOT PROVIDED]")
        p = d.add_paragraph()
        p.add_run(f"{title}: ").bold = True
        p.add_run(str(val))

    d.add_heading("Document Information", level=2)
    add_kv("Title", "document_title")
    add_kv("Document No.", "document_number")
    add_kv("Version", "version")
    add_kv("Date", "date")
    add_kv("Author", "author")
    add_kv("Reviewer", "reviewer")

    d.add_heading("Device Information", level=2)
    add_kv("Device Name", "device_name")
    add_kv("Device Model", "device_model")
    add_kv("Manufacturer", "manufacturer_name")

    d.add_heading("Completeness Summary", level=2)
    d.add_paragraph(f"Required fields present: {doc['completeness']['required_present']}/{doc['completeness']['required_total']}")
    d.add_paragraph(f"Completeness: {doc['completeness']['completeness_pct']}%")
    d.add_paragraph(f"Missing: {', '.join(doc['completeness']['missing_required']) or 'None'}")

    d.add_heading("Template-Aligned Fields", level=2)
    if template and template.get("fields"):
        d.add_paragraph(f"Template source: {template.get('filename','(unknown)')}")
        template_fields = template.get("fields", [])
    else:
        template_fields = schema["optional_fields"]
    for f in template_fields:
        add_kv(f, f)

    d.add_heading("Field Audit Trail", level=2)
    for field in schema["required_fields"] + schema["optional_fields"]:
        e = elements.get(field)
        if not e:
            continue
        d.add_paragraph(
            f"{field} | src={e.get('source')} | conf={int(e.get('confidence',0)*100)}% | ev: {str(e.get('evidence',''))[:120]}"
        )

    d.save(str(out_path))
    return out_path

# ── FastAPI ───────────────────────────────────────────────────────────────────
app = FastAPI(title="MedDoc Intake POC", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "groq_available": bool(get_groq()),
        "pdf_available": PDF_OK,
        "docx_available": DOCX_OK
    }

@app.post("/api/documents/upload")
async def upload_document(file: UploadFile = File(...)):
    content = await file.read()
    sha256  = hashlib.sha256(content).hexdigest()
    db = load_db()
    for doc_id, doc in db["documents"].items():
        if doc.get("sha256") == sha256:
            audit("upload_dedup",{"sha256":sha256,"existing":doc_id,"filename":file.filename})
            return {"doc_id":doc_id,"deduplicated":True,"message":"Already ingested."}
    doc_id = str(uuid.uuid4())
    ext    = Path(file.filename).suffix.lower()
    saved  = UPLOADS / f"{doc_id}{ext}"
    saved.write_bytes(content)
    mime_map = {".pdf":"application/pdf",".docx":"application/vnd.openxmlformats-officedocument.wordprocessingml.document",".txt":"text/plain"}
    mime = mime_map.get(ext,"text/plain")
    text     = extract_text(saved, mime)
    doc_type = detect_doc_type(text, file.filename)
    extracted, section_summary = section_aware_extract(text, doc_type)
    completeness = compute_completeness(doc_type, extracted)
    suggestions  = generate_suggestions(doc_id, doc_type, extracted, text)
    doc_node = {
        "doc_id":doc_id,"filename":file.filename,"sha256":sha256,
        "doc_type":doc_type,"uploaded_at":datetime.datetime.utcnow().isoformat(),
        "status":"extracted","text_length":len(text),
        "completeness":completeness,"suggestions":suggestions,
        "section_summary": section_summary
    }
    db["documents"][doc_id] = doc_node
    for field_name, field_data in extracted.items():
        elem_id = str(uuid.uuid4())
        db["elements"][elem_id] = {
            "elem_id":elem_id,"doc_id":doc_id,"field":field_name,
            "value":field_data["value"],"confidence":field_data["confidence"],
            "source":field_data["source"],"evidence":field_data["evidence"],
            "section": field_data.get("section", "Document-wide"),
            "edited":False,"edited_at":None
        }
        db["relationships"].append({"from":doc_id,"to":elem_id,"type":"has_field"})
        if field_name not in db["schema_registry"]:
            db["schema_registry"][field_name] = {"type":"string","docs_seen_in":[],"required_in":[]}
        reg = db["schema_registry"][field_name]
        if doc_id not in reg["docs_seen_in"]:
            reg["docs_seen_in"].append(doc_id)
        if doc_type not in reg.get("required_in",[]):
            if field_name in DOC_TYPES.get(doc_type,{}).get("required_fields",[]):
                reg.setdefault("required_in",[]).append(doc_type)
    rebuild_doc_element_relationships(db, doc_id, doc_type)
    save_db(db)
    audit("document_uploaded",{"doc_id":doc_id,"filename":file.filename,"doc_type":doc_type,"completeness_pct":completeness["completeness_pct"]})
    return {
        "doc_id":doc_id,"deduplicated":False,"doc_type":doc_type,
        "completeness":completeness,"field_count":len(extracted),
        "section_summary": section_summary
    }

@app.get("/api/documents")
def list_documents():
    db = load_db()
    docs = list(db["documents"].values())
    docs.sort(key=lambda d: d.get("uploaded_at", ""), reverse=True)
    pkg = package_completeness_summary(db)
    # Keep legacy key for UI compatibility; now points to output-doc coverage.
    return {
        "documents": docs,
        "package_completeness_pct": pkg["output_doc_coverage_pct"],
        "package": pkg
    }

@app.get("/api/package/completeness")
def package_completeness():
    db = load_db()
    return package_completeness_summary(db)

@app.get("/api/documents/{doc_id}")
def get_document(doc_id: str):
    db = load_db()
    doc = db["documents"].get(doc_id)
    if not doc:
        raise HTTPException(404,"Document not found")
    elements = [e for e in db["elements"].values() if e["doc_id"]==doc_id]
    elem_ids = {e["elem_id"] for e in elements}
    related = [r for r in db["relationships"] if r.get("type") == "field_related" and r.get("from") in elem_ids and r.get("to") in elem_ids]
    return {**doc,"elements":elements, "field_relationships": related}

class FieldEdit(BaseModel):
    elem_id: str
    new_value: str

@app.patch("/api/documents/{doc_id}/fields")
def edit_field(doc_id: str, body: FieldEdit):
    db = load_db()
    elem = db["elements"].get(body.elem_id)
    if not elem or elem["doc_id"]!=doc_id:
        raise HTTPException(404,"Element not found")
    old = elem["value"]
    elem["value"]    = body.new_value
    elem["edited"]   = True
    elem["edited_at"]= datetime.datetime.utcnow().isoformat()
    doc = db["documents"][doc_id]
    all_elems = {e["field"]:e for e in db["elements"].values() if e["doc_id"]==doc_id}
    doc["completeness"] = compute_completeness(doc["doc_type"],{f:{"value":e["value"]} for f,e in all_elems.items()})
    rebuild_doc_element_relationships(db, doc_id, doc["doc_type"])
    save_db(db)
    audit("field_edited",{"doc_id":doc_id,"field":elem["field"],"old":old,"new":body.new_value})
    return {"ok":True,"completeness":doc["completeness"]}

class SuggestionAction(BaseModel):
    action: str
    edited_value: Optional[str] = None

class ReprocessRequest(BaseModel):
    preserve_manual_edits: bool = True
    force_doc_type: Optional[str] = None

@app.post("/api/documents/{doc_id}/suggestions/{suggestion_id}")
def handle_suggestion(doc_id: str, suggestion_id: str, body: SuggestionAction):
    db = load_db()
    doc = db["documents"].get(doc_id)
    if not doc:
        raise HTTPException(404,"Document not found")
    sugg = next((s for s in doc["suggestions"] if s["id"]==suggestion_id),None)
    if not sugg:
        raise HTTPException(404,"Suggestion not found")
    sugg["status"] = body.action
    value_to_apply = None
    if body.action=="accept":
        value_to_apply = sugg["suggested_value"]
    elif body.action=="edit" and body.edited_value:
        sugg["suggested_value"] = body.edited_value
        value_to_apply = body.edited_value
    if value_to_apply is not None:
        elem_id = str(uuid.uuid4())
        db["elements"][elem_id] = {
            "elem_id":elem_id,"doc_id":doc_id,"field":sugg["field"],
            "value":value_to_apply,"confidence":1.0,
            "source":f"suggestion_{body.action}",
            "evidence":f"Suggestion: {sugg['rationale']}",
            "section":"Suggestions",
            "edited":body.action=="edit","edited_at":datetime.datetime.utcnow().isoformat()
        }
        db["relationships"].append({"from":doc_id,"to":elem_id,"type":"has_field"})
        all_elems = {e["field"]:e for e in db["elements"].values() if e["doc_id"]==doc_id}
        doc["completeness"] = compute_completeness(doc["doc_type"],{f:{"value":e["value"]} for f,e in all_elems.items()})
    rebuild_doc_element_relationships(db, doc_id, doc["doc_type"])
    save_db(db)
    audit("suggestion_actioned",{"doc_id":doc_id,"field":sugg["field"],"action":body.action})
    return {"ok":True,"completeness":doc["completeness"]}

@app.post("/api/documents/{doc_id}/reprocess")
def reprocess_document(doc_id: str, body: Optional[ReprocessRequest] = None):
    req = body or ReprocessRequest()
    db = load_db()
    doc = db["documents"].get(doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")

    # Find persisted uploaded source for this doc.
    matches = sorted(UPLOADS.glob(f"{doc_id}.*"))
    if not matches:
        raise HTTPException(404, "Original uploaded file not found for this document")
    src_path = matches[0]
    ext = src_path.suffix.lower()
    mime_map = {".pdf":"application/pdf",".docx":"application/vnd.openxmlformats-officedocument.wordprocessingml.document",".txt":"text/plain"}
    mime = mime_map.get(ext, "text/plain")
    text = extract_text(src_path, mime)
    doc_type = req.force_doc_type if req.force_doc_type else detect_doc_type(text, doc.get("filename",""))

    extracted, section_summary = section_aware_extract(text, doc_type)

    # Preserve manual/suggestion edits if requested.
    existing = [e for e in db["elements"].values() if e["doc_id"] == doc_id]
    if req.preserve_manual_edits:
        for e in existing:
            if e.get("edited") or str(e.get("source","")).startswith("suggestion_"):
                extracted[e["field"]] = {
                    "value": e.get("value",""),
                    "confidence": float(e.get("confidence",1.0)),
                    "source": e.get("source","manual_preserved"),
                    "evidence": e.get("evidence","Preserved from prior manual/suggestion action"),
                    "section": e.get("section","Manual edits")
                }

    # Remove old elements and their direct/field-related relationships.
    old_ids = {e["elem_id"] for e in existing}
    for elem_id in old_ids:
        db["elements"].pop(elem_id, None)
    db["relationships"] = [
        r for r in db["relationships"]
        if not ((r.get("from") in old_ids or r.get("to") in old_ids) and r.get("type") in {"has_field","field_related"})
    ]

    # Recreate elements from refreshed extraction.
    for field_name, field_data in extracted.items():
        elem_id = str(uuid.uuid4())
        db["elements"][elem_id] = {
            "elem_id":elem_id,"doc_id":doc_id,"field":field_name,
            "value":field_data["value"],"confidence":field_data["confidence"],
            "source":field_data["source"],"evidence":field_data["evidence"],
            "section": field_data.get("section", "Document-wide"),
            "edited": str(field_data.get("source","")).startswith("suggestion_"),
            "edited_at": datetime.datetime.utcnow().isoformat() if str(field_data.get("source","")).startswith("suggestion_") else None
        }
        db["relationships"].append({"from":doc_id,"to":elem_id,"type":"has_field"})

        reg = db["schema_registry"].setdefault(field_name, {"type":"string","docs_seen_in":[],"required_in":[]})
        reg.setdefault("docs_seen_in", [])
        reg.setdefault("required_in", [])
        if doc_id not in reg["docs_seen_in"]:
            reg["docs_seen_in"].append(doc_id)
        if field_name in DOC_TYPES.get(doc_type, {}).get("required_fields", []) and doc_type not in reg["required_in"]:
            reg["required_in"].append(doc_type)

    doc["doc_type"] = doc_type
    doc["text_length"] = len(text)
    doc["completeness"] = compute_completeness(doc_type, extracted)
    doc["suggestions"] = generate_suggestions(doc_id, doc_type, extracted, text)
    doc["section_summary"] = section_summary
    doc["status"] = "reprocessed"
    rebuild_doc_element_relationships(db, doc_id, doc_type)
    save_db(db)
    audit("document_reprocessed", {
        "doc_id": doc_id,
        "doc_type": doc_type,
        "preserve_manual_edits": req.preserve_manual_edits,
        "field_count": len(extracted)
    })
    return {
        "ok": True,
        "doc_id": doc_id,
        "doc_type": doc_type,
        "completeness": doc["completeness"],
        "field_count": len(extracted),
        "section_summary": section_summary
    }

@app.post("/api/documents/{doc_id}/generate")
def generate_output(doc_id: str):
    db = load_db()
    doc = db["documents"].get(doc_id)
    if not doc:
        raise HTTPException(404,"Document not found")
    elements = {e["field"]:e for e in db["elements"].values() if e["doc_id"]==doc_id}
    doc_type = doc["doc_type"]
    schema = effective_schema(db, doc_type)
    template = primary_template_for_doc_type(db, doc_type)
    lines = generate_output_lines(doc, elements, schema, template=template)
    out_path = OUTPUTS/f"{doc_id}_output.txt"
    out_path.write_text("\n".join(lines))
    doc["status"] = "output_generated"
    save_db(db)
    audit("output_generated",{"doc_id":doc_id})
    return {"ok":True,"download_url":f"/api/documents/{doc_id}/download"}

@app.post("/api/documents/{doc_id}/generate-docx")
def generate_output_docx(doc_id: str):
    db = load_db()
    doc = db["documents"].get(doc_id)
    if not doc:
        raise HTTPException(404,"Document not found")
    if not DOCX_OK:
        raise HTTPException(500,"DOCX generation dependency unavailable")
    elements = {e["field"]:e for e in db["elements"].values() if e["doc_id"]==doc_id}
    schema = effective_schema(db, doc["doc_type"])
    template = primary_template_for_doc_type(db, doc["doc_type"])
    out_path = write_output_docx(doc_id, doc, elements, schema, template=template)
    doc["status"] = "output_generated_docx"
    save_db(db)
    audit("output_generated_docx",{"doc_id":doc_id,"path":str(out_path)})
    return {"ok":True,"download_url":f"/api/documents/{doc_id}/download-docx"}

@app.get("/api/documents/{doc_id}/download")
def download_output(doc_id: str):
    out_path = OUTPUTS/f"{doc_id}_output.txt"
    if not out_path.exists():
        raise HTTPException(404,"Generate output first.")
    return FileResponse(str(out_path),filename=f"output_{doc_id[:8]}.txt",media_type="text/plain")

@app.get("/api/documents/{doc_id}/download-docx")
def download_output_docx(doc_id: str):
    out_path = OUTPUTS/f"{doc_id}_output.docx"
    if not out_path.exists():
        raise HTTPException(404,"Generate DOCX output first.")
    return FileResponse(
        str(out_path),
        filename=f"output_{doc_id[:8]}.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )

@app.get("/api/audit")
def get_audit(limit: int=100):
    if not AUDIT.exists():
        return {"events":[]}
    lines = AUDIT.read_text().strip().split("\n")
    events=[]
    for line in lines[-limit:]:
        try: events.append(json.loads(line))
        except: pass
    return {"events":list(reversed(events))}

@app.get("/api/schema")
def get_schema():
    db = load_db()
    return {
        "schema_registry":db["schema_registry"],
        "doc_types":list(DOC_TYPES.keys()),
        "template_count": len(db.get("templates", {})),
        "effective_doc_schemas": {dt: effective_schema(db, dt) for dt in DOC_TYPES.keys()},
        "section_taxonomy": SECTION_KEYWORDS
    }

class TemplateIngestRequest(BaseModel):
    filenames: Optional[List[str]] = None

@app.get("/api/templates")
def list_templates():
    db = load_db()
    templates = sorted(db.get("templates", {}).values(), key=lambda x: x.get("ingested_at",""), reverse=True)
    return {"templates": templates, "count": len(templates)}

@app.post("/api/templates/ingest")
def ingest_templates(body: Optional[TemplateIngestRequest] = None):
    filenames = body.filenames if body else None
    result = ingest_templates_into_ontology(filenames=filenames)
    return result

# ── Sample data loader ────────────────────────────────────────────────────────
SAMPLE_CEP_TEXT = """
CLINICAL EVALUATION PROTOCOL
Document Title: Clinical Evaluation Protocol - CardioTrack 3000
Document No.: CEP-CT3000-001
Version: 1.0
Date: 2024-03-15
Prepared by: Dr. Sarah Chen
Department: Regulatory Affairs & Clinical
Manufacturer: MedTech Solutions GmbH
Address: Innovationsstrasse 42, 80333 Munich, Germany

1. INTRODUCTION
This Clinical Evaluation Protocol (CEP) defines the methodology for the clinical evaluation
of the CardioTrack 3000 (Model: CT3000-EU), a continuous cardiac monitoring device
intended for use in adult patients in intensive care unit (ICU) settings.
The evaluation is conducted in accordance with MDR 2017/745, Annex XIV and MEDDEV 2.7/1 rev 4.

2. DEVICE DESCRIPTION
Device Name: CardioTrack 3000
Model: CT3000-EU
Device Classification: Class IIb, Rule 10 (MDR 2017/745)
Intended Purpose: Continuous cardiac monitoring for adult patients in ICU settings,
providing real-time ECG, heart rate, and arrhythmia detection alerts.

3. REGULATORY FRAMEWORK
Regulatory Framework: MDR 2017/745 (EU)
This evaluation follows the requirements of MDR 2017/745 Annex XIV Part A and MEDDEV 2.7/1 rev 4.

4. EVALUATION SCOPE
Scope: Full clinical evaluation per MEDDEV 2.7/1 rev 4 and MDR Annex XIV
The evaluation encompasses clinical performance, safety, and the benefit-risk profile.

5. LITERATURE SEARCH STRATEGY
Literature search: PubMed, Embase, Cochrane (2014-2024)
Search terms: cardiac monitoring, ICU telemetry, arrhythmia detection, continuous ECG.
Date range: January 2014 to March 2024.

6. INCLUSION CRITERIA
Inclusion criteria: RCTs and prospective cohort studies, at least 50 subjects, cardiac monitoring endpoint.
Studies must report sensitivity/specificity of arrhythmia detection.

7. CLINICAL DATA SOURCES
Clinical data sources: published literature, PMS data, clinical investigation CIP-CT3000-01
Post-market surveillance data from CardioTrack 2000 (predicate device) will also be included.

8. NOTES
This document requires completion of: exclusion criteria, equivalence device details,
benefit-risk assessment summary, and formal conclusions before submission.
""".strip()

@app.post("/api/demo/load-sample")
def load_sample():
    sha256 = hashlib.sha256(SAMPLE_CEP_TEXT.encode()).hexdigest()
    db = load_db()
    for doc_id,doc in db["documents"].items():
        if doc.get("sha256")==sha256:
            return {"doc_id":doc_id,"deduplicated":True}
    doc_id = str(uuid.uuid4())
    saved  = UPLOADS/f"{doc_id}.txt"
    saved.write_text(SAMPLE_CEP_TEXT)
    doc_type = "clinical_evaluation_protocol"
    extracted = {
        "document_title":    {"value":"Clinical Evaluation Protocol - CardioTrack 3000","confidence":1.0,"source":"sample_data","evidence":"Document Title: Clinical Evaluation Protocol - CardioTrack 3000","section":"Preamble"},
        "document_number":   {"value":"CEP-CT3000-001","confidence":1.0,"source":"sample_data","evidence":"Document No.: CEP-CT3000-001","section":"Preamble"},
        "version":           {"value":"1.0","confidence":1.0,"source":"sample_data","evidence":"Version: 1.0","section":"Preamble"},
        "date":              {"value":"2024-03-15","confidence":1.0,"source":"sample_data","evidence":"Date: 2024-03-15","section":"Preamble"},
        "device_name":       {"value":"CardioTrack 3000","confidence":1.0,"source":"sample_data","evidence":"Device Name: CardioTrack 3000","section":"DEVICE DESCRIPTION"},
        "device_model":      {"value":"CT3000-EU","confidence":1.0,"source":"sample_data","evidence":"Model: CT3000-EU","section":"DEVICE DESCRIPTION"},
        "manufacturer_name": {"value":"MedTech Solutions GmbH","confidence":1.0,"source":"sample_data","evidence":"Manufacturer: MedTech Solutions GmbH","section":"Preamble"},
        "regulatory_framework": {"value":"MDR 2017/745 (EU)","confidence":1.0,"source":"sample_data","evidence":"Regulatory Framework: MDR 2017/745","section":"REGULATORY FRAMEWORK"},
        "author":            {"value":"Dr. Sarah Chen","confidence":1.0,"source":"sample_data","evidence":"Prepared by: Dr. Sarah Chen","section":"Preamble"},
        "intended_purpose":  {"value":"Continuous cardiac monitoring for adult patients in ICU settings","confidence":0.9,"source":"sample_data","evidence":"Intended Purpose: Continuous cardiac monitoring...","section":"DEVICE DESCRIPTION"},
        "evaluation_scope":  {"value":"Full clinical evaluation per MEDDEV 2.7/1 rev 4 and MDR Annex XIV","confidence":0.9,"source":"sample_data","evidence":"Scope: Full clinical evaluation...","section":"EVALUATION SCOPE"},
        "literature_search_strategy": {"value":"Systematic search of PubMed, Embase, Cochrane (2014-2024)","confidence":0.9,"source":"sample_data","evidence":"Literature search: PubMed, Embase, Cochrane","section":"LITERATURE SEARCH STRATEGY"},
        "inclusion_criteria": {"value":"RCTs and prospective cohort studies, >=50 subjects, cardiac monitoring endpoint","confidence":0.9,"source":"sample_data","evidence":"Inclusion criteria: RCTs and prospective cohort studies","section":"INCLUSION CRITERIA"},
        "clinical_data_sources": {"value":"Published literature, PMS data, clinical investigation CIP-CT3000-01","confidence":0.9,"source":"sample_data","evidence":"Clinical data sources: published literature...","section":"CLINICAL DATA SOURCES"},
        "device_classification": {"value":"Class IIb, Rule 10 (MDR 2017/745)","confidence":0.9,"source":"sample_data","evidence":"Device Classification: Class IIb, Rule 10","section":"DEVICE DESCRIPTION"},
    }
    _, section_summary = section_aware_extract(SAMPLE_CEP_TEXT, doc_type)
    completeness = compute_completeness(doc_type, extracted)
    suggestions  = generate_suggestions(doc_id, doc_type, extracted, SAMPLE_CEP_TEXT)
    doc_node = {
        "doc_id":doc_id,"filename":"Sample_CEP_CardiacMonitor_v1.txt","sha256":sha256,
        "doc_type":doc_type,"uploaded_at":datetime.datetime.utcnow().isoformat(),
        "status":"extracted","text_length":len(SAMPLE_CEP_TEXT),
        "completeness":completeness,"suggestions":suggestions,
        "section_summary": section_summary
    }
    db["documents"][doc_id] = doc_node
    for field_name,field_data in extracted.items():
        elem_id = str(uuid.uuid4())
        db["elements"][elem_id] = {
            "elem_id":elem_id,"doc_id":doc_id,"field":field_name,
            "value":field_data["value"],"confidence":field_data["confidence"],
            "source":field_data["source"],"evidence":field_data["evidence"],
            "section": field_data.get("section", "Document-wide"),
            "edited":False,"edited_at":None
        }
        db["relationships"].append({"from":doc_id,"to":elem_id,"type":"has_field"})
        if field_name not in db["schema_registry"]:
            db["schema_registry"][field_name] = {"type":"string","docs_seen_in":[],"required_in":[]}
        db["schema_registry"][field_name]["docs_seen_in"].append(doc_id)
    rebuild_doc_element_relationships(db, doc_id, doc_type)
    save_db(db)
    audit("sample_loaded",{"doc_id":doc_id})
    return {"doc_id":doc_id,"deduplicated":False}
