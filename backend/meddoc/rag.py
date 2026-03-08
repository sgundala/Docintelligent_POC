from __future__ import annotations

import math
import re
from collections import Counter
from typing import Dict, List, Set

from .schemas import SECTION_FIELD_HINTS


TOKEN_RE = re.compile(r"[a-z0-9_]+")


def tokenize(text: str) -> List[str]:
    return TOKEN_RE.findall((text or "").lower())


def bow_vector(text: str) -> Counter:
    return Counter(tokenize(text))


def cosine(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    common = set(a.keys()) & set(b.keys())
    dot = sum(a[k] * b[k] for k in common)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def field_query(field: str) -> str:
    terms = [field.replace("_", " ")]
    synonyms = {
        "cytotoxicity": ["cytotoxicity", "in vitro cytotoxicity", "iso 10993-5"],
        "irritation": ["irritation", "intracutaneous reactivity", "iso 10993-10"],
        "sensitization": ["sensitization", "skin sensitization", "iso 10993-10"],
        "biocompatibility": ["biocompatibility", "biological evaluation", "iso 10993-1"],
        "biological_endpoints": ["biological endpoints", "endpoints evaluated", "biological evaluation plan"],
        "standard": ["iso 10993", "iso 10993-1", "iso 10993-5", "iso 10993-10"],
    }
    for key, vals in synonyms.items():
        if key in field:
            terms.extend(vals)
    return " ".join(terms)


def hinted_section_keys_for_field(field: str) -> Set[str]:
    keys: Set[str] = set()
    for skey, fields in SECTION_FIELD_HINTS.items():
        if field in fields:
            keys.add(skey)
    if not keys:
        keys.add("other")
    return keys


def retrieve_relevant_chunks(
    field: str,
    chunks: List[Dict[str, str]],
    k: int = 4
) -> List[Dict[str, str]]:
    q = bow_vector(field_query(field))
    hinted = hinted_section_keys_for_field(field)
    scored = []
    for ch in chunks:
        c = bow_vector(ch.get("text", ""))
        score = cosine(q, c)
        if ch.get("section_key") in hinted:
            score += 0.05
        scored.append((score, ch))
    scored.sort(key=lambda x: x[0], reverse=True)
    top = [c for s, c in scored if s > 0][:k]
    if top:
        return top
    return [c for _, c in scored[:k]]
