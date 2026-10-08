# Data Cleanup & Validation Pipeline

Turn 25,000 rows of realistically messy customer/CRM data into a clean, deduplicated
master file — plus a before/after data-quality scorecard, a fuzzy-dedup golden-record
merge, and a quarantine log of unfixable rows. **All cleaning rules live in one
`rules.yaml`; adding a rule is one line, not a code change.**

> The dataset is 100% **synthetic** (Faker, fixed seed). No real people, no real PII.
> This is a demo of the pipeline, not a real client engagement.

## What it does
1. **Ingest** a dirty CSV (mixed encodings, mojibake, mixed date/phone/currency formats,
   split/merged columns, duplicates).
2. **Profile (before)** — baseline data-quality across 6 DAMA dimensions.
3. **Clean & transform** every column by declarative rules (`rules.yaml`): dates →
   ISO 8601, phones → E.164, emails validated/normalized, currency → USD, country/source
   standardized, names split & title-cased, mojibake fixed.
4. **Validate & quarantine** — a bad field is nulled (and logged); a row with *no usable
   identifier* (no valid email AND no usable phone) is quarantined with a reason, never
   silently dropped.
5. **Fuzzy dedup** — multi-pass blocking + RapidFuzz weighted similarity + connected-
   components clustering + survivorship → one golden record per real person.
6. **Profile (after) + scorecard** and export the deliverables.

## Stack
`pandas` · `rapidfuzz` · `networkx` · `pandera` · `phonenumbers` · `email-validator` ·
`python-dateutil` · `charset-normalizer` · `ftfy` · `Unidecode` · `PyYAML` · `matplotlib` · `Faker`

Escalation paths (documented, not built for 25k): **Splink** for millions of rows /
probabilistic match weights, **dedupe** when the blocking key is unstable and labels
exist, **Great Expectations / soda-core** for team-wide data-quality governance.

## Run
```bash
pip install -r requirements.txt
python src/generate.py     # -> data/messy_customers_25k.csv (+ ground_truth, clean_reference)
python src/report.py       # -> out/01..04 + metrics.json  (clean, dedup, scorecard, metrics)
python src/visuals.py      # -> screens/*.png (portfolio slides)
```
Deterministic: a fixed seed means every run reproduces the same numbers.

## Outputs (`out/`)
| File | Contents |
|---|---|
| `01_Cleaned_Master.xlsx` | clean golden records (ISO dates, E.164 phones, USD, ISO country codes) |
| `02_Quarantine.xlsx` | unfixable rows + the reason each was isolated |
| `03_Change_Log.csv` | every field change: `record_id, column, rule, old_value, new_value` |
| `04_Data_Quality_Scorecard.xlsx` | 6 dimensions, before/after/delta + run summary |
| `metrics.json` | run facts + dedup/quarantine metrics verified vs ground truth |

## Last run (headline numbers)
- 25,000 input rows → **19,641** clean golden records
- **19.5%** duplicate rows merged · **611** rows quarantined (0 fixable records dropped)
- **103,558** field changes logged (real changes only; no-ops filtered out)
- Dedup **precision 99.9% / recall 94.9%** (measured against ground truth)
- Overall data-quality score **77% → 97%**

## Configuration
Edit `rules.yaml` to change behavior without touching code: per-column `clean` verbs,
`transform` types, `validate` rules + `on_fail` policy, the quarantine rule, and the
dedup blocking keys / field weights / threshold / survivorship strategy.
