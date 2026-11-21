"""HTTP API so other systems (an email workflow, n8n, Power Automate) can use ClerkAI.

    uvicorn clerkai.api:app --reload
    open http://localhost:8000/docs
"""

from __future__ import annotations

import os

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel

from .documents import SUPPORTED, read_bytes
from .config import load_env
from .llm import get_client

load_env()
from .pipeline import process_document
from .schemas import RunResult
from .store import RunStore

app = FastAPI(
    title="ClerkAI",
    description="AI triage for an accounting firm's shared inbox.",
    version="0.2.0",
)
_client = get_client()
_store = RunStore(os.getenv("CLERKAI_DB", "clerkai.db"))


class TextIn(BaseModel):
    text: str
    source: str = "api"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "llm": _client.name}


@app.post("/process", response_model=RunResult)
def process_text(body: TextIn) -> RunResult:
    if not body.text.strip():
        raise HTTPException(status_code=422, detail="text is empty")
    return process_document(body.text, body.source, _client, _store)


@app.post("/process/file", response_model=RunResult)
async def process_file(file: UploadFile = File(...)) -> RunResult:
    name = file.filename or "upload"
    if not name.lower().endswith(SUPPORTED):
        raise HTTPException(status_code=415, detail=f"supported types: {', '.join(SUPPORTED)}")
    text = read_bytes(await file.read(), name)
    if not text.strip():
        raise HTTPException(status_code=422, detail="no readable text (scanned image PDFs need OCR)")
    return process_document(text, name, _client, _store)


@app.get("/review-queue")
def review_queue() -> list[dict[str, object]]:
    return _store.review_queue()


@app.get("/stats")
def stats() -> dict[str, float]:
    return _store.stats()
