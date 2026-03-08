from __future__ import annotations

import re
from typing import Dict, List, Optional

from .schemas import SECTION_KEYWORDS


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


def chunk_text(
    text: str,
    sections: Optional[List[Dict[str, str]]] = None,
    max_chars: int = 1600
) -> List[Dict[str, str]]:
    src_sections = sections if sections is not None else extract_sections(text)
    chunks: List[Dict[str, str]] = []
    cidx = 0
    for sec in src_sections:
        body = sec.get("text", "")
        if not body.strip():
            continue
        start = 0
        while start < len(body):
            part = body[start:start + max_chars]
            chunks.append({
                "chunk_id": f"chunk_{cidx}",
                "heading": sec.get("heading", "Untitled"),
                "section_key": sec.get("section_key", "other"),
                "text": part.strip()
            })
            cidx += 1
            start += max_chars
    return chunks

