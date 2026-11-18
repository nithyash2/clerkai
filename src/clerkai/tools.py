"""Tools the agent can call: a client directory and a firm knowledge base.

Both run on local files so the demo needs no external systems. In a real firm
they would be swapped for the practice-management system and the firm's
procedure library, behind the same function signatures.
"""

from __future__ import annotations

import json
import math
import os
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(os.getenv("CLERKAI_DATA", Path(__file__).resolve().parents[2] / "data"))

_WORD = re.compile(r"[a-z0-9$]+")
_STOP = set("the a an and or of to in for on is are be with by at as it this that we our your you".split())


def _tokens(text: str) -> list[str]:
    return [t for t in _WORD.findall(text.lower()) if t not in _STOP]


@lru_cache(maxsize=1)
def _clients() -> list[dict[str, object]]:
    return json.loads((DATA_DIR / "clients.json").read_text(encoding="utf-8"))


def lookup_client(name: str) -> dict[str, object]:
    """Find a client record by business or contact name.

    Args:
        name: The client, business or contact name mentioned in the document.

    Returns:
        The client's record (entity type, assigned accountant, services, BAS
        frequency), or {"found": False} if no client matches.
    """
    query = set(_tokens(name))
    best, best_score = None, 0.0
    for c in _clients():
        names = [str(c["name"]), str(c["contact"]), *[str(a) for a in c.get("aliases", [])]]
        score = max(len(query & set(_tokens(n))) / max(len(set(_tokens(n))), 1) for n in names)
        if score > best_score:
            best, best_score = c, score
    if best is None or best_score < 0.5:
        return {"found": False}
    record = {k: v for k, v in best.items() if k != "aliases"}
    # TFN hashes stay inside ClerkAI: the agent only needs entity names and types.
    record["entities"] = [
        {k: v for k, v in e.items() if k in ("name", "type")} for e in best.get("entities", [])
    ]
    return {"found": True, **record}


@dataclass(frozen=True)
class _Doc:
    source: str
    text: str
    tokens: tuple[str, ...]


@lru_cache(maxsize=1)
def _knowledge() -> list[_Doc]:
    docs = []
    for path in sorted((DATA_DIR / "knowledge").glob("*.md")):
        text = path.read_text(encoding="utf-8")
        docs.append(_Doc(path.stem, text, tuple(_tokens(text))))
    return docs


def search_knowledge(query: str, top_k: int = 2) -> list[dict[str, str]]:
    """Search the firm's procedure notes for guidance relevant to a question.

    Args:
        query: What you need guidance on, for example "client wants to change bank details".
        top_k: How many procedure notes to return.

    Returns:
        The most relevant procedure notes, each with its source name and text.
    """
    docs = _knowledge()
    q = _tokens(query)
    n = len(docs)
    avg_len = sum(len(d.tokens) for d in docs) / max(n, 1)
    df = Counter(t for d in docs for t in set(d.tokens))

    def bm25(doc: _Doc, k1: float = 1.5, b: float = 0.75) -> float:
        tf = Counter(doc.tokens)
        score = 0.0
        for t in q:
            if t not in tf:
                continue
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            score += idf * tf[t] * (k1 + 1) / (tf[t] + k1 * (1 - b + b * len(doc.tokens) / avg_len))
        return score

    ranked = sorted(docs, key=bm25, reverse=True)
    return [{"source": d.source, "text": d.text} for d in ranked[:top_k] if bm25(d) > 0]
