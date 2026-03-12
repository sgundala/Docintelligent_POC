from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/api/health")
def health():
    import app as core

    return {
        "status": "ok",
        "groq_available": bool(core.get_groq()),
        "pdf_available": core.PDF_OK,
        "docx_available": core.DOCX_OK,
    }

