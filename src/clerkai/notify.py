"""Alerts to Slack (or the terminal) for documents that need a person, and for failures.

Set CLERKAI_SLACK_WEBHOOK to a Slack incoming-webhook URL. Without it, alerts are
printed, so the watcher still works on a laptop. Alerts carry the same masked reasons as
the run log: bank numbers appear only as their last three digits, never in full.
"""

from __future__ import annotations

import json
import os
import urllib.request
from collections.abc import Callable

from .schemas import RunResult

Sender = Callable[[str], None]


def _post_to_slack(text: str) -> None:
    url = os.environ["CLERKAI_SLACK_WEBHOOK"]
    req = urllib.request.Request(url, data=json.dumps({"text": text}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10):
        pass


def default_sender() -> Sender:
    if os.getenv("CLERKAI_SLACK_WEBHOOK"):
        return _post_to_slack
    return lambda text: print(f"[alert] {text}")


def needs_alert(r: RunResult) -> bool:
    return r.status == "failed" or r.decision.hold or r.decision.needs_review


def format_alert(r: RunResult, subject: str = "") -> str:
    d = r.decision
    if r.status == "failed":
        icon, headline = ":warning:", "Could not process automatically"
    elif d.hold:
        icon, headline = ":red_circle:", "PAYMENT HOLD"
    elif any("prompt injection" in x for x in d.reasons):
        icon, headline = ":shield:", "Possible manipulation attempt"
    else:
        icon, headline = ":large_yellow_circle:", "Needs review"
    doc = r.extraction.doc_type.value.replace("_", " ") if r.extraction else "document"
    lines = [f"{icon} *{headline}*: {doc} for {d.team} ({d.priority.value})"]
    if subject:
        lines.append(f"> {subject}")
    lines += [f"• {reason}" for reason in d.reasons[:4]]
    lines += [f":point_right: {task}" for task in d.tasks[:2]]
    return "\n".join(lines)


def format_failure(stage: str, error: Exception) -> str:
    return f":rotating_light: *ClerkAI failure* during {stage}: {type(error).__name__}: {error}"
