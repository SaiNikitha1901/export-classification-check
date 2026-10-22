"""Passage returned by the retriever (shared contract A.7)."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

PassageKind = Literal["gri", "section_note", "chapter_note", "heading", "tariff_line", "export_policy"]


class Passage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passage_id: str
    clause_id: str
    kind: PassageKind
    section: Optional[str] = None
    chapter: Optional[str] = None
    heading: Optional[str] = None
    title: Optional[str] = None
    text: str
    doc_id: str
    doc_version: Optional[str] = None
    page: Optional[int] = None
    score: Optional[float] = None
