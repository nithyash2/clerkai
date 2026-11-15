"""Command line: process a folder of documents and print a summary.

    python -m clerkai samples/
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .llm import get_client
from .pipeline import process_document
from .store import RunStore


def main() -> None:
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
