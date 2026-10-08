# data/labels/ · human labels for the per-check evaluation

`labels.csv` lists every check the agents make on the Pod's own cases (`data/input/my_cases.json`), one row per
(org, unit, stage, check). It does **not** show the agent's verdict, so labellers are not anchored by it.

1. Two members label **independently**: one fills `label_a`, the other `label_b`, with `PASS` or `FAIL` from the
   captures and order data (leave blank if it cannot be judged; say why in `notes`).
2. Score: `python scripts/score_checks.py data/labels/labels.csv` prints TP / TN / FP / FN per check (FAIL = positive),
   UNCERTAIN counts per label value, Cohen's kappa between the two people, and how many rows they disagreed on.
3. Paste the table into `docs/evaluation.md` with the method (who labelled, how, how many units).

Regenerate the sheet after adding cases: `python scripts/score_checks.py --template data/labels/labels.csv`
(this overwrites it: save filled labels first). Labels must come from real captures: placeholder images cannot be
labelled, so replace them first (see `data/input/README.md`).
