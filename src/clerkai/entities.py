"""Entity matching: file each document under the right entity of a client group.

One client often has several entities (an individual, a family trust, a company, an
SMSF) but sends everything from one email address, so the client's name alone does not
say where a document belongs. ClerkAI matches in order of strength:

  1. ABN in the document          -> exact entity (strong)
  2. TFN in the document          -> exact entity, compared as a salted hash (strong)
  3. A specific entity name       -> e.g. "Okafor Family Trust" or "... Pty Ltd"
  4. Only the person's name       -> client group found, entity unclear

When the entity is unclear for a document that affects someone's tax or books, the
document goes to a person with the candidate entities listed, instead of guessing.

This runs locally on the original text before masking. TFNs are never stored: the
client records hold only a salted SHA-256 hash, which is enough to recognise a match.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Literal

from pydantic import BaseModel, Field

from .masking import _TFN_CANDIDATE, is_valid_tfn
from .payments import _ABN, _digits
from .tools import DATA_DIR

# Demo salt. A real deployment would keep this secret (e.g. in a key vault).
TFN_SALT = os.getenv("CLERKAI_TFN_SALT", "clerkai-demo-salt")

Status = Literal["matched", "ambiguous", "none"]
Method = Literal["abn", "tfn", "name", "single_entity_client"]


class EntityMatch(BaseModel):
    status: Status = "none"
    entity: str | None = None
    entity_type: str | None = None
    client: str | None = None
    method: Method | None = None
    candidates: list[str] = Field(default_factory=list)


def tfn_hash(tfn: str) -> str:
    return hashlib.sha256((TFN_SALT + _digits(tfn)).encode()).hexdigest()


def _clients() -> list[dict]:
    return json.loads((DATA_DIR / "clients.json").read_text(encoding="utf-8"))


def _mentions(text: str, name: str) -> bool:
    return re.search(r"(?<!\w)" + re.escape(name.lower()) + r"(?!\w)", text) is not None


def _group_mentioned(text: str, client: dict) -> bool:
    names = [client["name"], client.get("contact", ""), *client.get("aliases", [])]
    names += [n for e in client.get("entities", []) for n in [e["name"], *e.get("aliases", [])]]
    return any(n and _mentions(text, n.lower()) for n in names)


def _strong(text: str, clients: list[dict], client: dict, entity: dict, method: Method) -> EntityMatch:
    """Trust an ABN or TFN match unless the document names a different client instead."""
    others = [c for c in clients if c is not client and _group_mentioned(text, c)]
    if others and not _group_mentioned(text, client):
        return EntityMatch(status="ambiguous", client=client["name"],
                           candidates=[entity["name"], *[o["name"] for o in others]])
    return _match(client, entity, method)


def _match(client: dict, entity: dict, method: Method) -> EntityMatch:
    return EntityMatch(status="matched", entity=entity["name"], entity_type=entity["type"],
                       client=client["name"], method=method)


def match_entity(text: str, client_name: str | None = None) -> EntityMatch:
    clients = _clients()
    lowered = text.lower()

    # 1-2. Strong identifiers: ABN, then TFN (as a hash).
    abns = {_digits(m.group(1)) for m in _ABN.finditer(text)}
    tfns = {tfn_hash(d) for d in ("".join(m.groups()) for m in _TFN_CANDIDATE.finditer(text)) if is_valid_tfn(d)}
    for c in clients:
        for e in c.get("entities", []):
            if e.get("abn") and _digits(e["abn"]) in abns:
                return _strong(lowered, clients, c, e, "abn")
    for c in clients:
        for e in c.get("entities", []):
            if e.get("tfn_sha256") and e["tfn_sha256"] in tfns:
                return _strong(lowered, clients, c, e, "tfn")

    # 3. Specific entity names (trusts, companies, funds) beat a bare person name.
    specific = [
        (c, e) for c in clients for e in c.get("entities", [])
        if e["type"] != "Individual"
        and any(_mentions(lowered, n) for n in [e["name"], *e.get("aliases", [])])
    ]
    if len(specific) == 1:
        c, e = specific[0]
        method: Method = "name" if len(c["entities"]) > 1 else "single_entity_client"
        return _match(c, e, method)
    if len(specific) > 1:
        return EntityMatch(status="ambiguous", client=specific[0][0]["name"],
                           candidates=[e["name"] for _, e in specific])

    # 4. Only the client or contact name: the group is known, the entity may not be.
    names_text = lowered + "\n" + (client_name or "").lower()
    for c in clients:
        group_names = [c["name"], c.get("contact", ""), *c.get("aliases", [])]
        group_names += [n for e in c.get("entities", []) for n in [e["name"], *e.get("aliases", [])]]
        if any(n and _mentions(names_text, n) for n in group_names):
            entities = c.get("entities", [])
            if len(entities) == 1:
                return _match(c, entities[0], "single_entity_client")
            return EntityMatch(status="ambiguous", client=c["name"],
                               candidates=[e["name"] for e in entities])
    return EntityMatch()
