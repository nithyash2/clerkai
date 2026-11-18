# Evaluation report: `gemini:gemini-3.8-flash,gemini-3.7-flash,gemini-3.5-flash-lite`

24 labelled documents (all synthetic).

| Metric | Score |
| --- | --- |
| Field accuracy: doc_type | 96% |
| Field accuracy: client_name | 100% |
| Field accuracy: amount | 100% |
| Field accuracy: due_date | 100% |
| Routing accuracy (team + priority + review) | 96% |
| Review recall (safety) | 100% |
| Review precision | 100% |
| Payment redirection caught (held) | 100% |
| False payment holds | 0 |
| Entity filing accuracy | 100% |
| Filed under the wrong entity | 0 |
| Sensitive values leaked to the LLM | 0 |
| Failed extractions | 0 |
| Latency p50 / p95 | 1322 ms / 119169 ms |

## Cases

| Document | Result | Notes |
| --- | --- | --- |
| 01_invoice_overdue.txt | pass |  |
| 02_invoice_high_value.txt | pass |  |
| 03_receipt.txt | pass |  |
| 04_ato_notice.txt | pass |  |
| 05_client_query.txt | pass |  |
| 06_unclear.txt | pass |  |
| 07_invoice_due_soon.txt | pass |  |
| 08_receipt_card.txt | pass |  |
| 09_ato_payment_reminder.txt | pass |  |
| 10_client_query_documents.txt | pass |  |
| 11_invoice_new_bank_details.txt | pass |  |
| 12_invoice_fitout.txt | pass |  |
| 13_receipt_rideshare.txt | pass |  |
| 14_client_query_with_tfn.txt | pass |  |
| 15_newsletter.txt | pass |  |
| 16_invoice_overdue_small.txt | pass |  |
| 17_invoice_silent_bank_change.txt | pass |  |
| 18_invoice_unknown_supplier.txt | pass |  |
| 19_invoice_known_details.txt | pass |  |
| 20_invoice_family_trust.txt | pass |  |
| 21_ato_notice_company_abn.txt | pass |  |
| 22_receipt_smsf_contribution.txt | pass |  |
| 23_receipt_laptop_unclear_entity.txt | FAIL | doc_type: expected 'receipt', got 'invoice'; priority: expected 'low', got 'normal' |
| 24_ato_notice_trustee.txt | pass |  |
