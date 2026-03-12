from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class FieldEdit(BaseModel):
    elem_id: str
    new_value: str


class SuggestionAction(BaseModel):
    action: str
    edited_value: Optional[str] = None


class ReprocessRequest(BaseModel):
    preserve_manual_edits: bool = True
    force_doc_type: Optional[str] = None


class TemplateIngestRequest(BaseModel):
    filenames: Optional[List[str]] = None

