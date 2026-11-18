"""Quality gate: the offline baseline must never get worse on privacy or safety."""

from clerkai.evaluate import evaluate, to_markdown
from clerkai.llm import OfflineClient


def test_offline_baseline_meets_quality_bar():
    summary, results = evaluate(OfflineClient())
    assert summary["cases"] == 27
    assert summary["leaks"] == 0  # no TFN, card or bank number ever reaches the LLM
    assert summary["review_recall"] == 1.0  # every risky document reaches a person
    assert summary["failures"] == 0
    assert summary["fraud_caught"] == 1.0  # every changed bank account is held
    assert summary["false_holds"] == 0  # correct details never trigger a hold
    assert summary["wrong_entity"] == 0  # never filed under the wrong entity
    assert summary["routing_accuracy"] >= 0.75
    assert "Routing accuracy" in to_markdown(summary, results, "offline-rules")
