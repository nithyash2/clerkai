"""Evaluation harness: measure how well the pipeline does on a labelled test set.

    python -m clerkai.evaluate                  # uses Gemini if a key is set, else offline
    python -m clerkai.evaluate --llm offline    # force the rule-based baseline
    python -m clerkai.evaluate --min-routing 0.9   # fail (exit 1) below a threshold, for CI

Each labelled document is run through the full pipeline and compared with the
expected answer. The report covers:
  - field accuracy (document type, client, amount, due date)
  - routing accuracy (team, priority and review decision all correct)
  - review recall: of the documents a person must see, how many were flagged.
    This is the safety metric: a missed review is worse than an extra one.
  - payment redirection: changed bank details caught, and false holds
  - privacy: whether any sensitive value from the document reached the LLM
  - failures and latency (p50 / p95)
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from .llm import LLMClient, OfflineClient, get_client
from .pipeline import process_document
from .tools import lookup_client

ROOT = Path(__file__).resolve().parents[2]
LABELS = ROOT / "evals" / "labels.json"
EVAL_TODAY = date(2026, 11, 10)  # labels for "overdue" and "due soon" assume this date
FIELDS = ("doc_type", "client_name", "amount", "due_date")


class SpyClient:
    """Wraps an LLM client and records every text it is sent, to check for leaks."""

    def __init__(self, inner: LLMClient) -> None:
        self.inner, self.sent = inner, []
        self.name = inner.name

    def extract(self, document: str, feedback: str | None = None) -> str:
        self.sent.append(document)
        return self.inner.extract(document, feedback)

    def __getattr__(self, attr: str) -> Any:  # pass run_agent etc. through
        return getattr(self.inner, attr)


def _canonical_client(name: str | None) -> str | None:
    if not name:
        return None
    record = lookup_client(name)
    return (record["name"] if record else name).strip().lower()


def _field_ok(name: str, expected: Any, got: Any) -> bool:
    if name == "amount":
        return got is not None and abs(float(got) - float(expected)) < 0.01
    if name == "client_name":
        return _canonical_client(got) == _canonical_client(expected)
    return str(got) == str(expected)


@dataclass
class CaseResult:
    file: str
    status: str
    latency_ms: float
    leaked: list[str]
    field_checks: dict[str, bool] = field(default_factory=dict)
    routing_ok: bool = False
    expected_review: bool = False
    flagged_review: bool = False
    expected_hold: bool = False
    held: bool = False
    mismatches: list[str] = field(default_factory=list)


def run_case(label: dict[str, Any], client: LLMClient) -> CaseResult:
    text = (ROOT / label["file"]).read_text(encoding="utf-8")
    spy = SpyClient(client)
    r = process_document(text, Path(label["file"]).name, spy, today=EVAL_TODAY, draft_replies=False)
    sent = "\n".join(spy.sent)
    res = CaseResult(
        file=Path(label["file"]).name,
        status=r.status,
        latency_ms=r.latency_ms,
        leaked=[s for s in label.get("secrets", []) if s in sent],
        expected_review=label["needs_review"],
        flagged_review=r.decision.needs_review,
        expected_hold=label.get("hold", False),
        held=r.decision.hold,
    )

    if r.status == "failed":
        res.mismatches.append(f"EXTRACTION FAILED: {r.error}")
    ex = r.extraction.model_dump(mode="json") if r.extraction else {}
    for name in FIELDS:
        if name in label:
            ok = _field_ok(name, label[name], ex.get(name))
            res.field_checks[name] = ok
            if not ok:
                res.mismatches.append(f"{name}: expected {label[name]!r}, got {ex.get(name)!r}")

    got_route = {
        "team": r.decision.team,
        "priority": r.decision.priority.value,
        "needs_review": r.decision.needs_review,
        "hold": r.decision.hold,
    }
    route_ok = True
    for key, got in got_route.items():
        if key in label and label[key] != got:
            route_ok = False
            res.mismatches.append(f"{key}: expected {label[key]!r}, got {got!r}")
    res.routing_ok = route_ok
    if res.leaked:
        res.mismatches.append(f"LEAKED to LLM: {res.leaked}")
    return res


def summarise(results: list[CaseResult]) -> dict[str, Any]:
    def rate(values: list[bool]) -> float:
        return sum(values) / len(values) if values else 1.0

    must_review = [r for r in results if r.expected_review]
    flagged = [r for r in results if r.flagged_review]
    latencies = sorted(r.latency_ms for r in results)
    p95_index = max(0, round(0.95 * len(latencies)) - 1)
    return {
        "cases": len(results),
        "field_accuracy": {
            name: rate([r.field_checks[name] for r in results if name in r.field_checks])
            for name in FIELDS
        },
        "routing_accuracy": rate([r.routing_ok for r in results]),
        "review_recall": rate([r.flagged_review for r in must_review]),
        "review_precision": rate([r.expected_review for r in flagged]),
        "fraud_caught": rate([r.held for r in results if r.expected_hold]),
        "false_holds": sum(r.held and not r.expected_hold for r in results),
        "leaks": sum(len(r.leaked) for r in results),
        "failures": sum(r.status == "failed" for r in results),
        "latency_p50_ms": statistics.median(latencies) if latencies else 0.0,
        "latency_p95_ms": latencies[p95_index] if latencies else 0.0,
    }


def to_markdown(summary: dict[str, Any], results: list[CaseResult], llm: str) -> str:
    fa = summary["field_accuracy"]
    lines = [
        f"# Evaluation report: `{llm}`",
        "",
        f"{summary['cases']} labelled documents (all synthetic).",
        "",
        "| Metric | Score |",
        "| --- | --- |",
        *[f"| Field accuracy: {k} | {v:.0%} |" for k, v in fa.items()],
        f"| Routing accuracy (team + priority + review) | {summary['routing_accuracy']:.0%} |",
        f"| Review recall (safety) | {summary['review_recall']:.0%} |",
        f"| Review precision | {summary['review_precision']:.0%} |",
        f"| Payment redirection caught (held) | {summary['fraud_caught']:.0%} |",
        f"| False payment holds | {summary['false_holds']} |",
        f"| Sensitive values leaked to the LLM | {summary['leaks']} |",
        f"| Failed extractions | {summary['failures']} |",
        f"| Latency p50 / p95 | {summary['latency_p50_ms']:.0f} ms / {summary['latency_p95_ms']:.0f} ms |",
        "",
        "## Cases",
        "",
        "| Document | Result | Notes |",
        "| --- | --- | --- |",
    ]
    for r in results:
        ok = r.routing_ok and all(r.field_checks.values()) and not r.leaked
        lines.append(f"| {r.file} | {'pass' if ok else 'FAIL'} | {'; '.join(r.mismatches) or ''} |")
    return "\n".join(lines) + "\n"


def evaluate(client: LLMClient, labels_path: Path = LABELS) -> tuple[dict[str, Any], list[CaseResult]]:
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    results = [run_case(label, client) for label in labels]
    return summarise(results), results


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate ClerkAI on the labelled test set.")
    parser.add_argument("--llm", choices=["auto", "offline"], default="auto")
    parser.add_argument("--out", type=Path, default=ROOT / "evals" / "report.md")
    parser.add_argument("--min-routing", type=float, default=0.0, help="exit 1 below this")
    parser.add_argument("--min-review-recall", type=float, default=0.0, help="exit 1 below this")
    args = parser.parse_args()

    client = OfflineClient() if args.llm == "offline" else get_client()
    summary, results = evaluate(client)
    if summary["failures"] == summary["cases"]:
        first = next(r for r in results if r.status == "failed")
        print("Every extraction failed, so the scores below are not meaningful.")
        print("First error:", next(m for m in first.mismatches if m.startswith("EXTRACTION FAILED")))
        print("Check GEMINI_API_KEY and GEMINI_MODEL, then run again.\n")
    report = to_markdown(summary, results, client.name)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report, encoding="utf-8")
    print(report)
    print(f"Report saved to {args.out}")

    failed = (
        summary["routing_accuracy"] < args.min_routing
        or summary["review_recall"] < args.min_review_recall
        or summary["leaks"] > 0
        or summary["fraud_caught"] < 1.0
    )
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
