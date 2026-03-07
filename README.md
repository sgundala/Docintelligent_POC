# Take-Home: Document Intake → Completeness → Intelligent Fill (POC)

## Goal

Build a small, end-to-end proof of concept:

- User uploads one or more PDF/docx documents
- System detects document type and extracts structured fields
- UI allows the user to review and edit extracted fields with evidence
- System computes completeness per document and package-level across multiple documents
- System proposes intelligent suggestions to fill missing required fields
- User accepts / edits / rejects suggestions
- System generates draft output documents plus audit artifacts for traceability

Make reasonable assumptions and document them.

## Inputs (Provided)

- 2 example “customer uploads” in /uploads
- 4 documents in /outputdocs, which you may treat as reference templates/example outputs

## UI Expectations (Lightweight)

A simple web UI that supports:
- Uploading or selecting a document
- Viewing extracted fields with evidence
- Reviewing suggestions for missing fields (accept / edit / reject)
- Generating and viewing/downloading a draft output
- Viewing completeness (progress/coverage)

## Core Requirements

1. Completeness
- Show completeness % per output document
- Show completeness % across all output documents
- Surface missing required fields

2. Traceability & Auditability
- For every extracted field and every suggestion, show why
- Log key events (timestamped). Logs may be stored however you choose (file, DB, etc.).

3. Repeatability
- Re-running ingestion should not create duplicates. You decide how this is handled. Document your choice.

## Ontology / Structure Requirement

The backend should store information in a way that supports:
- Linking document → extracted elements → evidence
- Linking elements to each other when relevant (you define relationships)
- Being “self-evolving” such that (1) New uploads can introduce new terms, fields, or relationships, (2) This does not require rewriting large portions of the system
  This does not need to be a perfect ontology, we are looking for a clear approach, not completeness.

## You Decide
- What the data structure / schema / ontology looks like
- How it evolves as new documents are added
- How suggestions are generated: Heuristics vs. embeddings vs. LLMs

## Deliverables
- GitHub repository with working code
- README documenting (1) How to run the system (Docker preferred) (2) Architecture overview and data model / ontology design (3) Key tradeoffs and assumptions (4) What is AI vs. what is deterministic (5) Anticipated scaling bottlenecks

## Timebox
- 3 hours of active work
- Repository access will remain open for 24 hours for flexibility
