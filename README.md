# MedDoc Intake POC (AI-Based)

Document Intake -> Review -> Intelligent Fill -> Completeness

> Submission note: this repository update is an **AI-based additional implementation pass** for the take-home, and is **not intended to replace prior baseline work/history**.

A Docker-first proof of concept for medical/regulatory document workflows:
- Upload one or more PDF/DOCX/TXT files
- Detect document type
- Extract structured fields with evidence/provenance
- Review/edit fields
- Accept/edit/reject suggestions
- Compute completeness (document + package + output-template matrix)
- Generate draft outputs (TXT/DOCX)
- Maintain audit trail and evolving ontology

## Contents
- [1. Quick Start](#1-quick-start)
- [2. What This Project Covers](#2-what-this-project-covers)
- [3. Architecture](#3-architecture)
- [4. Data Model and Ontology](#4-data-model-and-ontology)
- [5. Extraction Pipeline (Section + RAG)](#5-extraction-pipeline-section--rag)
- [6. Completeness Model](#6-completeness-model)
- [7. API Endpoints](#7-api-endpoints)
- [8. UI Walkthrough](#8-ui-walkthrough)
- [9. Running End-to-End Validation](#9-running-end-to-end-validation)
- [10. AI vs Deterministic Logic](#10-ai-vs-deterministic-logic)
- [11. Tradeoffs and Assumptions](#11-tradeoffs-and-assumptions)
- [12. Scaling Bottlenecks](#12-scaling-bottlenecks)
- [13. Troubleshooting](#13-troubleshooting)
- [14. Project Structure](#14-project-structure)
- [15. GitHub Push Steps](#15-github-push-steps)

## 1. Quick Start

### Prerequisites
- Docker Desktop / Docker Engine running
- Ports `3000` and `8000` free
- Optional: Groq API key for better extraction quality

### Start
```bash
cd /Users/sivadatum/Documents/Playground/Accelidea_Siva
cp .env.example .env
# edit .env and set GROQ_API_KEY=... (optional but recommended)
docker compose up --build -d
```

### Open
- UI: [http://localhost:3000](http://localhost:3000)
- Health: [http://localhost:8000/api/health](http://localhost:8000/api/health)

### Stop
```bash
docker compose down
```

## 2. What This Project Covers

### In scope
- Dockerized full-stack app (React + FastAPI)
- Ingestion with deduplication (SHA-256)
- Extraction with Groq + fallback heuristics
- Section-aware extraction and section-level coverage
- Suggestion workflow: accept / edit / reject
- Document/package/output-template completeness
- Output generation and download (`.txt`, `.docx`)
- Audit log and schema/ontology registry

### Out of scope
- Authentication/authorization
- Load/performance testing
- Production-grade OCR for image-only scans
- Formal graph DB (uses JSON graph store)

## 3. Architecture

```text
Browser (React)
  -> Upload, field review, suggestions, generation, traceability
  -> Calls REST API

FastAPI Backend
  -> Ingestion + dedup
  -> Type detection
  -> Section/chunking + retrieval + extraction
  -> Suggestions + completeness + output generation
  -> Audit logging
  -> JSON ontology store

Storage
  -> ontology_data/ontology_db.json
  -> logs/audit.jsonl
  -> uploads/, outputs/
```

Groq is used when available. If Groq errors or rate-limits, the backend fails open to heuristic extraction (upload still succeeds).

## 4. Data Model and Ontology

Ontology is a self-evolving JSON graph in `ontology_data/ontology_db.json`.

### Core entities
- `documents`: uploaded docs and summary metadata
- `elements`: extracted fields with provenance/evidence
- `templates`: ingested sample/output templates
- `relationships`:
  - `has_field` (document -> element)
  - `template_defines_field` (template -> field name)
  - `field_related` (element -> element semantic relation)
- `schema_registry`: observed/evolving field catalog

### Provenance tracked per field
- `source` (e.g. `groq_llm`, `groq_rag`, `heuristic_regex`, `heuristic_rag`, `suggestion_accept`)
- `confidence`
- `evidence`
- `section` (where it came from)

## 5. Extraction Pipeline (Section + RAG)

Implemented in modular backend package `backend/meddoc`:
- `schemas.py`: doc schemas + section field hints
- `chunking.py`: heading detection + section extraction + chunking
- `rag.py`: in-memory lexical retrieval scoring
- `pipeline.py`: section-aware extraction orchestration

### Flow
1. Parse document text into sections
2. Create chunks per section
3. Run broad extraction (Groq + heuristic fallback)
4. For missing fields, retrieve top relevant chunks and run targeted extraction
5. Build section summary:
   - expected required coverage
   - actual extracted fields by section
   - misaligned required fields

### Biocompatibility pack
Added fields include:
- `biocompatibility_standard`
- `biological_endpoints_evaluated`
- `biocompatibility_assessment`
- `cytotoxicity_result`
- `sensitization_result`
- `irritation_result`

## 6. Completeness Model

### A. Document completeness
For selected document type:
- `required_present / required_total * 100`

### B. Package completeness
- Output doc type coverage across uploaded package

### C. Output-template completeness matrix
Per template row:
- matched doc
- required fields present/total
- missing field count/list
- `completeness_pct`
- `matched_doc_filename`, `matched_doc_uploaded_at`

UI supports `Show only incomplete rows` in package card.

## 7. API Endpoints

### Health
- `GET /api/health`

### Documents
- `POST /api/documents/upload`
- `GET /api/documents`
- `GET /api/documents/{id}`
- `PATCH /api/documents/{id}/fields`
- `POST /api/documents/{id}/reprocess`

### Suggestions
- `POST /api/documents/{id}/suggestions/{sid}`

### Output
- `POST /api/documents/{id}/generate`
- `GET /api/documents/{id}/download`
- `POST /api/documents/{id}/generate-docx`
- `GET /api/documents/{id}/download-docx`

### Audit / Schema / Templates
- `GET /api/audit`
- `GET /api/schema`
- `GET /api/package/completeness`
- `GET /api/templates`
- `POST /api/templates/ingest`

### Demo
- `POST /api/demo/load-sample`

## 8. UI Walkthrough

### Left sidebar
- Upload zone
- Package completeness card + output-template rows
- Document list (newest first)
- Audit panel

### Main document view tabs
- `Fields`: extracted values + confidence + source + section
- `Sections`: section coverage and extracted-here lists
- `Suggestions`: pending + resolved (accept/edit/reject)
- `Missing`: missing required fields
- `Templates`: template-derived field coverage
- `Traceability`: hash, status, provenance

Behavior improvements:
- Auto-selects first/newest document
- New upload auto-focuses on newest document

## 9. Running End-to-End Validation

### Manual flow
1. Start stack: `docker compose up --build -d`
2. Check health (`/api/health`)
3. Upload a document in UI
4. Open document -> inspect fields/suggestions/sections/missing
5. Action suggestions (accept/edit/reject)
6. Edit at least one field
7. Generate output and download
8. Verify audit events
9. Re-upload same file to verify dedup

### Quick API smoke examples
```bash
curl -s http://localhost:8000/api/health
curl -s http://localhost:8000/api/documents
curl -s http://localhost:8000/api/package/completeness
curl -s http://localhost:8000/api/schema
```

## 10. AI vs Deterministic Logic

### AI-driven
- Groq extraction for structured field values
- Groq-based missing field suggestion generation
- RAG-targeted extraction for missing fields from relevant chunks

### Deterministic
- SHA-256 dedup
- regex/heuristic extraction fallback
- completeness scoring arithmetic
- output assembly
- audit logging
- ontology append/update semantics

## 11. Tradeoffs and Assumptions

### Tradeoffs
- JSON file store is simple but not high-scale
- In-memory retrieval is lightweight but not semantic vector retrieval
- Template mining from raw PDFs can be noisy without stronger normalization
- No auth (POC)

### Assumptions
- English-language docs
- Extractable text is available (not image-only scan)
- One file primarily maps to one doc type

## 12. Scaling Bottlenecks

- JSON ontology file growth (I/O contention)
- Groq rate limits / cost
- No async job queue for heavy extraction
- In-memory retrieval not cross-document semantic search
- PDF table extraction still heuristic for complex layouts

Suggested production path:
- PostgreSQL + vector DB (pgvector/Qdrant)
- Worker queue (Celery/RQ)
- robust OCR/table parsing layer
- auth + multi-tenant scoping

## 13. Troubleshooting

### Upload seems static / UI unchanged
- Hard refresh `Cmd+Shift+R`
- Ensure newest doc appears in left list
- Check dedup response (same bytes -> no new doc)

### Upload fails with Groq rate limit
- Backend now falls back automatically
- Check `logs/audit.jsonl` for `groq_request_error`

### Only package card visible
- Click a document in left list
- Main tabs appear when a doc is selected

### Containers healthy?
```bash
docker compose ps
docker compose logs backend --tail=120
docker compose logs frontend --tail=120
```

## 14. Project Structure

```text
Accelidea_Siva/
├── backend/
│   ├── app.py
│   ├── requirements.txt
│   └── meddoc/
│       ├── __init__.py
│       ├── schemas.py
│       ├── chunking.py
│       ├── rag.py
│       └── pipeline.py
├── frontend/
│   └── src/
│       ├── App.js
│       ├── App.css
│       └── ...
├── sample_docs/
├── uploads/
├── outputs/
├── logs/
├── Dockerfile.backend
├── Dockerfile.frontend
├── docker-compose.yml
└── README.md
```

## 15. GitHub Push Steps

Run from project root:

```bash
cd /Users/sivadatum/Documents/Playground/Accelidea_Siva
git status
git add .
git commit -m "Finalize MedDoc intake POC: modular extraction, completeness matrix, UI fixes, README"
```

If remote is not set:
```bash
git remote add origin <YOUR_GITHUB_REPO_URL>
```

Push:
```bash
git branch -M main
git push -u origin main
```

If you prefer a feature branch:
```bash
git checkout -b codex/readme-final
git push -u origin codex/readme-final
```
