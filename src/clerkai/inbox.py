"""Inbox watcher: process new emails automatically, alert people, never process twice.

    python -m clerkai watch            # check every 60 seconds until stopped
    python -m clerkai watch --once     # check once and exit (for a scheduler or cron)

Settings (in .env, never committed):
    CLERKAI_IMAP_HOST       default imap.gmail.com
    CLERKAI_IMAP_USER       the demo inbox address
    CLERKAI_IMAP_PASSWORD   a Gmail App Password (not the account password)
    CLERKAI_SLACK_WEBHOOK   optional; without it alerts are printed

How it works: each check logs in over IMAP (SSL), fetches UNSEEN messages, and turns
each one into documents: every supported attachment (PDF, text, email) is processed with
the sender and subject added for context, or the email body if there are none. Results
go to the run log, people get an alert for anything held, flagged or failed, and the
message is marked as read. Message-IDs are recorded in the database, so a message is
never processed twice even if marking it as read fails or the watcher restarts.
"""

from __future__ import annotations

import email
import imaplib
import os
import time
from collections.abc import Callable
from email import policy
from email.message import EmailMessage

from .documents import SUPPORTED, read_bytes
from .notify import Sender, default_sender, format_alert, format_failure, needs_alert
from .pipeline import process_document
from .store import RunStore

FAILURES_BEFORE_ALERT = 3  # consecutive failed checks before a failure alert is sent


def connect() -> imaplib.IMAP4_SSL:
    conn = imaplib.IMAP4_SSL(os.getenv("CLERKAI_IMAP_HOST", "imap.gmail.com"))
    conn.login(os.environ["CLERKAI_IMAP_USER"], os.environ["CLERKAI_IMAP_PASSWORD"])
    return conn


def documents_from(msg: EmailMessage) -> list[tuple[str, str]]:
    """Split one email into (source name, text) documents."""
    header = f"From: {msg['from']}\nSubject: {msg['subject']}\n\n"
    docs = []
    for part in msg.iter_attachments():
        name = part.get_filename() or "attachment"
        if any(name.lower().endswith(ext) for ext in SUPPORTED):
            text = read_bytes(part.get_payload(decode=True) or b"", name)
            if text.strip():
                docs.append((name, header + text))
    if not docs:
        body = msg.get_body(preferencelist=("plain", "html"))
        content = body.get_content() if body else ""
        docs.append(("email body", header + content))
    return docs


def check_inbox(
    client: object,
    store: RunStore,
    conn_factory: Callable[[], object] = connect,
    send: Sender | None = None,
) -> int:
    """Process every unseen message once. Returns the number of documents processed."""
    send = send or default_sender()
    conn = conn_factory()
    processed = 0
    try:
        conn.select("INBOX")
        _, data = conn.search(None, "UNSEEN")
        for num in data[0].split():
            _, parts = conn.fetch(num, "(BODY.PEEK[])")
            msg = email.message_from_bytes(parts[0][1], policy=policy.default)
            message_id = str(msg["message-id"] or f"no-id-{num.decode()}")
            if store.already_processed(message_id):
                conn.store(num, "+FLAGS", "\\Seen")
                continue
            subject = str(msg["subject"] or "(no subject)")
            for source, text in documents_from(msg):
                r = process_document(text, f"email: {subject} / {source}", client, store)
                processed += 1
                if needs_alert(r):
                    send(format_alert(r, subject))
            store.mark_processed(message_id, subject)
            conn.store(num, "+FLAGS", "\\Seen")
    finally:
        try:
            conn.logout()
        except Exception:
            pass
    return processed


def watch(client: object, store: RunStore, interval: int = 60, once: bool = False,
          conn_factory: Callable[[], object] = connect, send: Sender | None = None,
          sleep: Callable[[float], None] = time.sleep) -> None:
    send = send or default_sender()
    failures = 0
    while True:
        try:
            n = check_inbox(client, store, conn_factory, send)
            if failures >= FAILURES_BEFORE_ALERT:
                send(":white_check_mark: ClerkAI inbox watcher has recovered.")
            failures = 0
            print(f"[{time.strftime('%H:%M:%S')}] checked inbox: {n} new document(s)")
        except Exception as exc:  # keep watching; alert once if it keeps failing
            failures += 1
            print(f"[{time.strftime('%H:%M:%S')}] check failed ({failures}): {exc}")
            if failures == FAILURES_BEFORE_ALERT:
                send(format_failure("inbox check", exc))
            if once:
                raise
        if once:
            return
        sleep(interval)
