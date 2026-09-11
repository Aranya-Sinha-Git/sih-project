# Screenshot evidence index

The CUA browser captured and displayed the following screenshots inline during the acceptance run. The available browser surface did not provide a supported way to materialize the returned screenshot bytes as repository PNG files. These captures corroborate the DOM/API evidence; they are not used as the sole persistence proof.

| Capture | Page/state | UTC context | Corroborating evidence |
|---|---|---|---|
| `dashboard_initial` | Deployed dashboard with authenticated workspace metrics before acceptance writes | Early acceptance flow | `raw_evidence.json#browser_auth_dashboard` |
| `primary_analysis` | New deployed analysis detail for `ANL-AE471CFB`, including score, route, narrative, grounded evidence | After analysis completion | `raw_evidence.json#browser_primary_analysis` |
| `queue_before` | Review queue with exactly one Pending fixture `ANL-6BF36018` | Before escalation | `raw_evidence.json#browser_queue_before` |
| `review_persisted_detail` | Fixture detail after reload/navigation showing Escalated / Unsure and Demo Reviewer | After escalation persistence | `raw_evidence.json#browser_review_persisted_navigation` |
| `dashboard_after` | Dashboard after escalation with pending=1 and unresolved/escalated=1 | After transition | `raw_evidence.json#browser_dashboard_after` |
| `queue_after` | Review queue after escalation with the same one fixture still actionable | After transition | `raw_evidence.json#browser_queue_after` |
| `primary_provenance` | Primary detail with Assigned Life-Saving Rules, Retrieved reference concepts, unavailable coverage, and expanded stored technical provenance | Read-only provenance check | `raw_evidence.json#browser_primary_persisted_detail` |
| `partial_record` | Pre-existing `ANL-B1BECD47` partial/historical record with no current assignment provenance | Read-only legacy/partial check | `raw_evidence.json#browser_partial_record` |
| `model_and_settings` | Deployed model identity/hash and threshold settings | Integrity check | `raw_evidence.json#browser_model_page`, `raw_evidence.json#browser_settings_page` |
