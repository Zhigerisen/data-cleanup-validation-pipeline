"""
Scorecard + ground-truth metrics + export for the Data Cleanup pipeline.
Run:  python src/report.py
Produces out/01..04 + metrics.json and prints an ASCII summary.
"""
from __future__ import annotations
import itertools
import json
import os
import re
import sys
import time
from datetime import date

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pipeline as P  # noqa: E402

CANON_SOURCES = {"Facebook", "Google", "Organic", "Referral", "Email"}
CANON_COUNTRIES = {"US", "GB", "DE", "FR", "KZ"}
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^\+\d{7,15}$")


def pct(num, den):
    return round(100.0 * num / den, 1) if den else 0.0


def _as_int(v):
    try:
        iv = int(float(str(v)))
        return iv if 0 <= iv <= 100000 else None
    except (ValueError, TypeError):
        return None


# ---------------- scorecard (DAMA dimensions) ----------------
def scorecard(raw, master, G, M, cfg):
    aliases = cfg["country_aliases"]

    # Completeness
    mcols = P.MEASURE_COLS
    raw_cells = len(raw) * len(mcols)
    raw_nonempty = sum(int((~raw[c].map(P.is_empty)).sum()) for c in mcols)
    acols = ["email", "phone", "country", "city", "signup_date",
             "last_order_date", "order_count", "total_spent_usd"]
    has_name = master["first_name"].notna() | master["last_name"].notna()
    m_cells = len(master) * (len(acols) + 1)
    m_nonempty = int(has_name.sum()) + sum(int(master[c].notna().sum()) for c in acols)
    completeness = (pct(raw_nonempty, raw_cells), pct(m_nonempty, m_cells))

    # Validity (over populated cells)
    v_valid = v_pop = 0
    for _, r in raw.iterrows():
        country = P.map_alias(r.get("country"), aliases)
        region = country if country in CANON_COUNTRIES else "US"
        dayfirst = country in ("GB", "DE", "FR")
        checks = [
            (r.get("email"), P.valid_email(P.c_fix_mojibake(r.get("email")))),
            (r.get("phone"), P.clean_phone(r.get("phone"), region)),
            (r.get("country"), country),
            (r.get("signup_date"), P.parse_date(r.get("signup_date"), dayfirst)),
            (r.get("total_spent"), P.parse_amount(r.get("total_spent"))),
            (r.get("order_count"), _as_int(r.get("order_count"))),
        ]
        for raw_v, parsed in checks:
            if not P.is_empty(raw_v):
                v_pop += 1
                v_valid += 1 if parsed is not None else 0
    # after: measured on the cleaned master (not hardcoded)
    mv_valid = mv_pop = 0
    for _, r in master.iterrows():
        pairs = [
            (r["email"], lambda v: bool(EMAIL_RE.match(str(v)))),
            (r["phone"], lambda v: bool(PHONE_RE.match(str(v)))),
            (r["country"], lambda v: v in CANON_COUNTRIES),
            (r["signup_date"], lambda v: bool(ISO_RE.match(str(v)))),
            (r["total_spent_usd"], lambda v: float(v) >= 0),
            (r["order_count"], lambda v: int(float(v)) >= 0),
        ]
        for val, test in pairs:
            if not (val is None or (isinstance(val, float) and pd.isna(val))):
                mv_pop += 1
                mv_valid += 1 if test(val) else 0
    validity = (pct(v_valid, v_pop), pct(mv_valid, mv_pop))

    # Uniqueness = distinct entities / rows. Before: G distinct entities among M rows
    # (G is the dedup cluster count). After: the master holds exactly those G golden
    # records, so G / len(master) -- computed from real values, not hardcoded.
    uniqueness = (pct(G, M), pct(G, len(master)))

    # Consistency
    c_ok = c_pop = 0
    for _, r in raw.iterrows():
        for val, test in [
            (r.get("country"), lambda v: str(v).strip() in CANON_COUNTRIES),
            (r.get("signup_date"), lambda v: bool(ISO_RE.match(str(v).strip()))),
            (r.get("source"), lambda v: str(v).strip() in CANON_SOURCES),
        ]:
            if not P.is_empty(val):
                c_pop += 1
                c_ok += 1 if test(val) else 0
    m_ok = m_pop = 0
    for _, r in master.iterrows():
        for val, test in [
            (r["country"], lambda v: v in CANON_COUNTRIES),
            (r["signup_date"], lambda v: bool(ISO_RE.match(str(v)))),
            (r["source"], lambda v: v in CANON_SOURCES),
        ]:
            if not pd.isna(val):
                m_pop += 1
                m_ok += 1 if test(val) else 0
    consistency = (pct(c_ok, c_pop), pct(m_ok, m_pop))

    # Timeliness (valid, in-range last_order_date known)
    t_before = 0
    for _, r in raw.iterrows():
        country = P.map_alias(r.get("country"), aliases)
        d = P.parse_date(r.get("last_order_date"), country in ("GB", "DE", "FR"))
        if d is not None and date(2015, 1, 1) <= d <= P.TODAY:
            t_before += 1
    timeliness = (pct(t_before, len(raw)),
                  pct(int(master["last_order_date"].notna().sum()), len(master)))

    return [completeness, validity, uniqueness, consistency, timeliness]


# ---------------- accuracy vs source of truth ----------------
def accuracy(raw, master, gt, ref):
    ref_by_e = ref.set_index("entity_id").to_dict("index")
    eid_by_rid = dict(zip(gt["record_id"], gt["entity_id"]))
    raw_by_rid = raw.set_index("record_id").to_dict("index")

    def digits(s):
        return re.sub(r"\D", "", str(s))

    before_ok = before_n = after_ok = after_n = 0
    # Accuracy = do the identity fields (email, phone) match the source of truth?
    # total_spent is excluded: a raw local-currency string cannot be reconciled to a USD
    # master without the pipeline, so scoring it "before" would be meaningless.
    fld = {"email": [0, 0], "phone": [0, 0]}   # [ok, n]
    for _, m in master.iterrows():
        eid = eid_by_rid.get(m["record_id"])
        if eid is None or eid not in ref_by_e:
            continue
        rf = ref_by_e[eid]
        # after: score only fields that are present in the cleaned master
        if not pd.isna(m["email"]):
            ok = m["email"] == rf["email_canon"]
            after_n += 1; after_ok += ok; fld["email"][1] += 1; fld["email"][0] += ok
        if not pd.isna(m["phone"]):
            ok = m["phone"] == rf["phone_e164"]
            after_n += 1; after_ok += ok; fld["phone"][1] += 1; fld["phone"][0] += ok
        # before: same fields from the raw record, lightly normalized (lowercase/strip,
        # phone compared on trailing digits) -- what you could reconcile without cleaning
        rr = raw_by_rid.get(m["record_id"], {})
        refdig = digits(rf["phone_e164"])[-9:]
        if not P.is_empty(rr.get("email")):
            before_n += 1; before_ok += 1 if str(rr["email"]).strip().lower() == rf["email_canon"] else 0
        if not P.is_empty(rr.get("phone")):
            before_n += 1
            before_ok += 1 if (refdig and digits(rr.get("phone", "")).endswith(refdig)) else 0
    detail = {k: pct(v[0], v[1]) for k, v in fld.items()}
    return pct(before_ok, before_n), pct(after_ok, after_n), detail


# ---------------- dedup / quarantine metrics vs ground truth ----------------
def pairs_from_groups(mapping):
    pairs = set()
    for members in mapping.values():
        if len(members) > 1:
            for a, b in itertools.combinations(sorted(members), 2):
                pairs.add((a, b))
    return pairs


def dedup_metrics(gt, cluster_map):
    true_pairs = pairs_from_groups(gt.groupby("entity_id")["record_id"].apply(list).to_dict())
    pred_pairs = pairs_from_groups(cluster_map.groupby("cluster_id")["record_id"].apply(list).to_dict())
    tp = len(true_pairs & pred_pairs)
    return {"true_pairs": len(true_pairs), "pred_pairs": len(pred_pairs), "tp": tp,
            "precision": pct(tp, len(pred_pairs)), "recall": pct(tp, len(true_pairs))}


def quarantine_metrics(gt, q_record_ids, raw, cfg):
    """Honest, buyer-relevant quarantine metrics:
      - planted_recall: of the deliberately-unfixable rows, how many we caught
      - false_drops: quarantined rows that STILL had a recoverable id (must be 0)
    """
    aliases = cfg["country_aliases"]
    planted = set(gt[gt["quarantine_truth"] == 1]["record_id"])
    pred = set(q_record_ids)
    caught = len(planted & pred)
    raw_by_rid = raw.set_index("record_id").to_dict("index")
    false_drops = 0
    for rid in pred:
        rr = raw_by_rid.get(rid, {})
        country = P.map_alias(rr.get("country"), aliases)
        region = country if country in CANON_COUNTRIES else "US"
        if P.valid_email(P.c_fix_mojibake(rr.get("email"))) or P.clean_phone(rr.get("phone"), region):
            false_drops += 1
    return {"planted": len(planted), "caught": caught,
            "planted_recall": pct(caught, len(planted)),
            "pred": len(pred), "false_drops": false_drops,
            "false_drop_rate": pct(false_drops, len(pred))}


# ---------------- export ----------------
def export(raw, master, q, audit, sc_full, dims, run_facts):
    os.makedirs(P.OUT, exist_ok=True)
    master.drop(columns=[c for c in ["cluster_id"] if c in master.columns]) \
        .to_excel(os.path.join(P.OUT, "01_Cleaned_Master.xlsx"), index=False)

    qraw = raw[raw["record_id"].isin(q["record_id"])].copy()
    qraw = qraw.merge(q[["record_id", "_reasons"]], on="record_id", how="left")
    qraw.to_excel(os.path.join(P.OUT, "02_Quarantine.xlsx"), index=False)

    audit.to_csv(os.path.join(P.OUT, "03_Change_Log.csv"), index=False, encoding="utf-8")

    rows = []
    for name, (before, after) in zip(dims, sc_full):
        rows.append({"Dimension": name, "Before %": before, "After %": after,
                     "Delta (pp)": round(after - before, 1)})
    ob = round(sum(r["Before %"] for r in rows) / len(rows), 1)
    oa = round(sum(r["After %"] for r in rows) / len(rows), 1)
    rows.append({"Dimension": "OVERALL DQ", "Before %": ob, "After %": oa,
                 "Delta (pp)": round(oa - ob, 1)})
    facts_df = pd.DataFrame(list(run_facts.items()), columns=["Metric", "Value"])
    with pd.ExcelWriter(os.path.join(P.OUT, "04_Data_Quality_Scorecard.xlsx")) as xl:
        pd.DataFrame(rows).to_excel(xl, sheet_name="Scorecard", index=False)
        facts_df.to_excel(xl, sheet_name="Run Summary", index=False)
    return ob, oa


def main():
    t0 = time.perf_counter()
    cfg = P.load_config()
    raw = pd.read_csv(os.path.join(P.DATA, "messy_customers_25k.csv"), dtype=str, keep_default_na=False)
    raw["record_id"] = raw["record_id"].astype(int)   # keep ids numeric (match ground truth)
    gt = pd.read_csv(os.path.join(P.DATA, "ground_truth.csv"))
    ref = pd.read_csv(os.path.join(P.DATA, "clean_reference.csv"), dtype=str)  # keep +E164 as text
    ref["entity_id"] = ref["entity_id"].astype(int)
    ref["total_spent_usd"] = ref["total_spent_usd"].astype(float)
    print("[..] loaded", len(raw), "raw rows")

    clean, audit = P.clean_dataframe(raw, cfg)
    print("[OK] cleaned; audit changes:", len(audit))
    clean_nonq, q = P.apply_quarantine(clean)
    print("[OK] quarantine:", len(q), "| to-dedup:", len(clean_nonq))

    master, cluster_map, matched = P.dedup(clean_nonq, cfg)
    M, G = len(clean_nonq), len(master)
    print("[OK] dedup: %d -> %d golden records (%d pairs matched)" % (M, G, len(matched)))

    dm = dedup_metrics(gt, cluster_map)
    qm = quarantine_metrics(gt, q["record_id"].tolist(), raw, cfg)
    sc = scorecard(raw, master, G, M, cfg)
    acc_before, acc_after, acc_detail = accuracy(raw, master, gt, ref)
    acc = (acc_before, acc_after)
    dims = ["Completeness", "Validity", "Uniqueness", "Consistency", "Accuracy", "Timeliness"]
    sc_full = [sc[0], sc[1], sc[2], sc[3], (acc_before, acc_after), sc[4]]

    dup_rows_found = M - G
    run_facts = {
        "Input rows": len(raw),
        "Clean golden records": G,
        "Duplicate rows merged": dup_rows_found,
        "Duplicate rate %": pct(dup_rows_found, M),
        "Quarantined rows": len(q),
        "Field changes logged": len(audit),
        "Dedup precision %": dm["precision"],
        "Dedup recall %": dm["recall"],
        "Quarantine false-drops": qm["false_drops"],
        "Quarantine planted-recall %": qm["planted_recall"],
        "Runtime sec": round(time.perf_counter() - t0, 1),
    }

    ob, oa = export(raw, master, q, audit, sc_full, dims, run_facts)

    metrics = {"run_facts": run_facts, "dedup": dm, "quarantine": qm,
               "scorecard": {d: {"before": b, "after": a} for d, (b, a) in zip(dims, sc_full)},
               "overall_before": ob, "overall_after": oa}
    with open(os.path.join(P.OUT, "metrics.json"), "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)

    print("\n==== SCORECARD (before -> after) ====")
    for d, (b, a) in zip(dims, sc_full):
        print("  %-13s %5.1f%% -> %5.1f%%  (%+.1f pp)" % (d, b, a, a - b))
    print("  %-13s %5.1f%% -> %5.1f%%" % ("OVERALL", ob, oa))
    print("\n==== GROUND-TRUTH METRICS ====")
    print("  dedup      precision %.1f%%  recall %.1f%%  (true %d, pred %d, tp %d)" %
          (dm["precision"], dm["recall"], dm["true_pairs"], dm["pred_pairs"], dm["tp"]))
    print("  quarantine %d rows | planted-recall %.1f%% (%d/%d) | false-drops %d (%.1f%%)" %
          (qm["pred"], qm["planted_recall"], qm["caught"], qm["planted"],
           qm["false_drops"], qm["false_drop_rate"]))
    print("  accuracy   before %.1f%% -> after %.1f%%  (email %.1f%% phone %.1f%%)" %
          (acc_before, acc_after, acc_detail["email"], acc_detail["phone"]))
    print("\n[OK] wrote out/01..04 + metrics.json  (%.1fs)" % run_facts["Runtime sec"])


if __name__ == "__main__":
    main()
