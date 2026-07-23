"""
Note tools — search (semantic/keyword) and save.

``search_notes`` is read-only. ``save_note`` is a write action requiring approval.
"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field, field_validator

from app.database.models import NoteCreate
from app.tools.registry import ToolContext, register_tool


# --------------------------------------------------------------- search_notes
class SearchNotesInput(BaseModel):
    query: str = Field(..., min_length=1, description="What to search for.")
    category: str | None = Field(None, description="Optional category filter.")
    date_from: date | None = Field(None, description="Only notes created on/after this date.")
    date_to: date | None = Field(None, description="Only notes created on/before this date.")
    semantic: bool = Field(True, description="Semantic (meaning-based) search vs keyword match.")
    limit: int = Field(5, ge=1, le=20)


class NoteHit(BaseModel):
    note_id: str
    title: str
    snippet: str
    category: str
    tags: list[str] = Field(default_factory=list)
    score: float


class SearchNotesOutput(BaseModel):
    matches: list[NoteHit]
    count: int


@register_tool(
    name="search_notes",
    description=(
        "Search the user's saved notes and return the most relevant ones with a match score. Use "
        "for 'find my notes about the marketing campaign', 'what did I write about onboarding'. "
        "Semantic search (default) matches by meaning; set semantic=false for exact keyword match. "
        "READ-ONLY; no approval needed."
    ),
    input_model=SearchNotesInput,
    output_model=SearchNotesOutput,
    is_write=False,
    requires_approval=False,
)
def search_notes(inp: SearchNotesInput, ctx: ToolContext) -> SearchNotesOutput:
    if inp.semantic:
        results = ctx.repo.search_notes_semantic(
            inp.query, k=inp.limit, category=inp.category,
            date_from=inp.date_from, date_to=inp.date_to,
        )
    else:
        results = ctx.repo.search_notes_keyword(inp.query, k=inp.limit)
    hits = [
        NoteHit(
            note_id=str(m.note.id),
            title=m.note.title,
            snippet=m.note.content[:200] + ("..." if len(m.note.content) > 200 else ""),
            category=m.note.category,
            tags=m.note.tags,
            score=round(m.score, 4),
        )
        for m in results
    ]
    return SearchNotesOutput(matches=hits, count=len(hits))


# ----------------------------------------------------------------- save_note
class SaveNoteInput(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    content: str = Field(..., min_length=1)
    category: str = Field("general", description="e.g. meeting, idea, reference.")
    tags: list[str] = Field(default_factory=list)

    @field_validator("title", "content")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be blank")
        return v.strip()


class SaveNoteOutput(BaseModel):
    note_id: str
    title: str
    confirmation: str


@register_tool(
    name="save_note",
    description=(
        "Save a NEW note (title + content, optional category and tags) so it can be searched later. "
        "Use for 'save this as a note', 'remember that ...'. Its embedding is computed automatically "
        "for semantic search. WRITE action; requires approval. Do NOT use to create actionable "
        "tasks — use create_task for those."
    ),
    input_model=SaveNoteInput,
    output_model=SaveNoteOutput,
    is_write=True,
    requires_approval=True,
)
def save_note(inp: SaveNoteInput, ctx: ToolContext) -> SaveNoteOutput:
    note = ctx.repo.save_note(
        NoteCreate(title=inp.title, content=inp.content, category=inp.category, tags=inp.tags)
    )
    return SaveNoteOutput(
        note_id=str(note.id),
        title=note.title,
        confirmation=f"Saved note '{note.title}' in category '{note.category}'.",
    )
