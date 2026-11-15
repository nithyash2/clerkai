"""Read inbox attachments into plain text (PDF, TXT, EML)."""

from __future__ import annotations

import io
from email import policy
from email.parser import BytesParser
from pathlib import Path

SUPPORTED = (".txt", ".pdf", ".eml", ".md")


def read_bytes(data: bytes, filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    if suffix == ".eml":
        msg = BytesParser(policy=policy.default).parsebytes(data)
        body = msg.get_body(preferencelist=("plain", "html"))
        content = body.get_content() if body else ""
        return f"From: {msg['from']}\nSubject: {msg['subject']}\n\n{content}".strip()
    return data.decode("utf-8", errors="replace")


def read_path(path: str | Path) -> str:
    p = Path(path)
    return read_bytes(p.read_bytes(), p.name)
