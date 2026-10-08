# Provenance · Recovery Manager

- **Owner:** Vishruth Jeelakapally (@vishruth-16)
- **Original Repository:** https://github.com/vishruth-16/https-github.com-Cube-Build-A-Thon-cube-05-recovery-manager
- **Commit SHA:** `794c2c54c3feab96adbfc216086d0567ab64dc91` (latest commit on `main`, 2026-10-01). **Confirmed by the owner (@vishruth-16) as the submitted Round 2 commit** in his approving review of PR #7 on 2026-10-08.
- **What was brought over:** the tri-state fee audit (CONTRADICTS / SUPPORTS / SILENT) and its evidence-status mapping, and the tenancy guard, re-expressed as per-charge-type rules in `app.py`. Round 2's claim-window (60 days), duplicate-charge and already-reimbursed checks are **not** in the Round 3 version: the sample fee report has no duplicate or reimbursement-id fields, and the claim window was not re-implemented against `posted_date`.
- **What changed for Round 3:** the deprecated `google.generativeai` SDK was replaced; default mode is deterministic rules (`model.name = "rules"`); the optional live mode uses `google-genai` with one batched call per unit, and a model claim must cite a real upstream record (D-013).
