"""Tests never use real services: no Gemini calls, no Slack posts, no inbox logins,
even when a developer's local .env holds real keys (load_env never overrides a value
that is already set, including an empty one)."""

import os

os.environ["CLERKAI_LLM"] = "offline"
for key in ("CLERKAI_SLACK_WEBHOOK", "CLERKAI_IMAP_USER", "CLERKAI_IMAP_PASSWORD"):
    os.environ[key] = ""
