from __future__ import annotations

from typing import Callable, Dict, List, Optional, Set, Tuple

from .chunking import extract_sections, chunk_text
from .rag import retrieve_relevant_chunks
from .schemas import SECTION_FIELD_HINTS


ExtractFn = Callable[[str, str, List[str], str, str], Dict[str, Dict]]
HeuristicFn = Callable[[str, str, Optional[Set[str]], str, str], Dict[str, Dict]]


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


def build_section_summary(
    sections: List[Dict[str, str]],
    required_fields: List[str],
    extracted: Dict[str, Dict]
) -> List[Dict[str, object]]:
    section_map: Dict[str, Dict[str, object]] = {}
    heading_to_key: Dict[str, str] = {}
    for sec in sections:
        heading_to_key[sec["heading"]] = sec["section_key"]
        section_map[sec["heading"]] = {
            "heading": sec["heading"],
            "section_key": sec["section_key"],
            "required_present": 0,
            "required_total": 0,
            "fields_present": [],
            "expected_required_fields": [],
            "misaligned_required_fields": [],
        }
    expected_section_by_field: Dict[str, str] = {}
    for field in required_fields:
        section_key = next((k for k, vals in SECTION_FIELD_HINTS.items() if field in vals), "other")
        expected_section_by_field[field] = section_key
        candidate_sections = [s for s in sections if s["section_key"] == section_key]
        target_heading = candidate_sections[0]["heading"] if candidate_sections else "Preamble"
        section_map.setdefault(target_heading, {
            "heading": target_heading, "section_key": section_key,
            "required_present": 0, "required_total": 0,
            "fields_present": [], "expected_required_fields": [], "misaligned_required_fields": []
        })
        section_map[target_heading]["required_total"] += 1
        section_map[target_heading]["expected_required_fields"].append(field)
        if field in extracted and str(extracted[field].get("value", "")).strip():
            section_map[target_heading]["required_present"] += 1

    for field, data in extracted.items():
        if not str(data.get("value", "")).strip():
            continue
        observed_heading = str(data.get("section", "Document-wide")) or "Document-wide"
        observed_key = heading_to_key.get(observed_heading, "other")
        section_map.setdefault(observed_heading, {
            "heading": observed_heading, "section_key": observed_key,
            "required_present": 0, "required_total": 0,
            "fields_present": [], "expected_required_fields": [], "misaligned_required_fields": []
        })
        section_map[observed_heading]["fields_present"].append(field)
        if field in expected_section_by_field and observed_key != expected_section_by_field[field]:
            section_map[observed_heading]["misaligned_required_fields"].append(field)

    out = []
    for item in section_map.values():
        total = int(item["required_total"])
        present = int(item["required_present"])
        pct = round((present / total) * 100, 1) if total else 0.0
        out.append({**item, "completeness_pct": pct})
    out.sort(key=lambda x: (x["required_total"] == 0, x["heading"]))
    return out


def section_aware_extract_rag(
    text: str,
    doc_type: str,
    all_fields: List[str],
    required_fields: List[str],
    use_groq: bool,
    groq_extract_fields: ExtractFn,
    heuristic_extract: HeuristicFn,
) -> Tuple[Dict[str, Dict], List[Dict[str, object]]]:
    sections = extract_sections(text)
    chunks = chunk_text(text, sections=sections)
    extracted: Dict[str, Dict] = {}

    required_set = set(required_fields)
    field_priority = sorted(all_fields, key=lambda f: (f not in required_set, f))
    max_rag_llm_calls = 10
    rag_llm_calls = 0

    if use_groq and text.strip():
        extracted = merge_extracted_values(
            extracted,
            groq_extract_fields(text, doc_type, all_fields, "groq_llm", "Document-wide")
        )
        extracted = merge_extracted_values(
            extracted,
            heuristic_extract(text, doc_type, set(all_fields), "heuristic_regex", "Document-wide")
        )
        for field in field_priority:
            if field in extracted:
                continue
            if rag_llm_calls >= max_rag_llm_calls:
                break
            rel_chunks = retrieve_relevant_chunks(field, chunks, k=3)
            if not rel_chunks:
                continue
            context = "\n\n".join(
                f"[{c.get('heading','')}] {c.get('text','')}" for c in rel_chunks if c.get("text")
            )
            llm_hit = groq_extract_fields(context, doc_type, [field], "groq_rag", rel_chunks[0].get("heading", "RAG"))
            rag_llm_calls += 1
            extracted = merge_extracted_values(extracted, llm_hit)
            if field not in extracted:
                h = heuristic_extract(context, doc_type, {field}, "heuristic_rag", rel_chunks[0].get("heading", "RAG"))
                extracted = merge_extracted_values(extracted, h)
    else:
        extracted = merge_extracted_values(
            extracted,
            heuristic_extract(text, doc_type, set(all_fields), "heuristic_regex", "Document-wide")
        )
        for field in field_priority:
            if field in extracted:
                continue
            rel_chunks = retrieve_relevant_chunks(field, chunks, k=3)
            if not rel_chunks:
                continue
            context = "\n\n".join(
                f"[{c.get('heading','')}] {c.get('text','')}" for c in rel_chunks if c.get("text")
            )
            h = heuristic_extract(context, doc_type, {field}, "heuristic_rag", rel_chunks[0].get("heading", "RAG"))
            extracted = merge_extracted_values(extracted, h)

    section_summary = build_section_summary(sections, required_fields, extracted)
    return extracted, section_summary
