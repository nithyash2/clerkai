"""Command line.

    python -m clerkai samples/         process a folder of documents and print a summary
    python -m clerkai watch            watch the demo inbox and process new emails
    python -m clerkai watch --once     check the inbox once and exit
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import load_env
from .llm import get_client
from .pipeline import process_document
from .store import RunStore


def watch_main(argv: list[str]) -> None:
    from .inbox import watch

    parser = argparse.ArgumentParser(prog="clerkai watch", description="Watch the inbox.")
    parser.add_argument("--interval", type=int, default=60, help="seconds between checks")
    parser.add_argument("--once", action="store_true", help="check once and exit")
    parser.add_argument("--db", default="clerkai.db", help="SQLite run log path")
    args = parser.parse_args(argv)
    client = get_client()
    print(f"LLM: {client.name}. Watching {args.interval}s; press Ctrl+C to stop.")
    try:
        watch(client, RunStore(args.db), interval=args.interval, once=args.once)
    except KeyboardInterrupt:
        print("Stopped.")


def main() -> None:
    load_env()
    if len(sys.argv) > 1 and sys.argv[1] == "watch":
        watch_main(sys.argv[2:])
        return
    parser = argparse.ArgumentParser(description="Triage an accounting inbox with AI.")
    parser.add_argument("folder", type=Path, help="Folder of .txt documents")
    parser.add_argument("--db", default="clerkai.db", help="SQLite run log path")
    args = parser.parse_args()

    client = get_client()
    store = RunStore(args.db)
    print(f"LLM: {client.name}\n")
    print(f"{'document':<26}{'type':<14}{'team':<17}{'priority':<9}{'review':<8}reasons")
    print("-" * 110)

    for path in sorted(args.folder.glob("*.txt")):
        r = process_document(path.read_text(encoding="utf-8"), path.name, client, store)
        doc_type = r.extraction.doc_type.value if r.extraction else "FAILED"
        d = r.decision
        print(
            f"{path.name:<26}{doc_type:<14}{d.team:<17}{d.priority.value:<9}"
            f"{'yes' if d.needs_review else 'no':<8}{'; '.join(d.reasons)}"
        )

    s = store.stats()
    print(
        f"\nRuns: {s['runs']:.0f} | failure rate: {s['failure_rate']:.0%} | "
        f"review rate: {s['review_rate']:.0%} | avg latency: {s['avg_latency_ms']:.0f} ms | "
        f"PII values masked: {s['pii_masked']:.0f}"
    )


if __name__ == "__main__":
    main()
