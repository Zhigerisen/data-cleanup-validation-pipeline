"""
Data Cleanup & Validation Pipeline -- engine.

Ingest -> profile(before) -> configurable clean/transform/validate -> quarantine
-> fuzzy dedup (blocking + rapidfuzz + connected components + survivorship)
-> profile(after) -> export workbook + scorecard + audit log + metrics.json

All rules live in rules.yaml; adding a rule = editing YAML, not code.
Run:  python src/pipeline.py
ASCII-only console output (Windows cp1251 safe).
"""
from __future__ import annotations
import json
import os
import re
import unicodedata
from datetime import date, datetime

import networkx as nx
import pandas as pd
import phonenumbers
import yaml
from dateutil import parser as dateparser
from email_validator import EmailNotValidError, validate_email
from ftfy import fix_text
from rapidfuzz import fuzz
from unidecode import unidecode

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
OUT = os.path.join(HERE, "out")
TODAY = date(2026, 10, 6)

MEASURE_COLS = ["name", "email", "phone", "country", "city",
                "signup_date", "last_order_date", "order_count", "total_spent"]
EMPTY_TOKENS = {"", "n/a", "na", "-", "--", "null", "none", "tbd", "yesterday"}


# ========================= config =========================
def load_config():
    with open(os.path.join(HERE, "rules.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


# ========================= cleaners =========================
def c_strip(s):
    return s.strip() if isinstance(s, str) else s


def c_lower(s):
    return s.lower() if isinstance(s, str) else s


def c_upper(s):
    return s.upper() if isinstance(s, str) else s


def c_collapse_ws(s):
    if not isinstance(s, str):
        return s
    s = unicodedata.normalize("NFKC", s)
    return re.sub(r"\s+", " ", s).strip()


def c_fix_mojibake(s):
    return fix_text(s) if isinstance(s, str) and s else s


def c_ascii_fold(s):
    return unidecode(s) if isinstance(s, str) else s


def c_titlecase_smart(s):
    if not isinstance(s, str) or not s:
        return s
    parts = []
    for w in s.split():
        if w.lower() in ("llc", "kg", "gmbh", "ltd", "inc"):
            parts.append(w.upper())
        elif "'" in w and len(w) > 2:               # O'Brien
            a, b = w.split("'", 1)
            parts.append(a.capitalize() + "'" + b.capitalize())
        else:
            parts.append(w.capitalize())
    return " ".join(parts)


_ADDR = {r"\bSt\.?\b": "Street", r"\bAve\.?\b": "Avenue", r"\bRd\.?\b": "Road",
         r"\bBlvd\.?\b": "Boulevard", r"\bDr\.?\b": "Drive", r"\bLn\.?\b": "Lane"}


def c_expand_address_abbr(s):
    if not isinstance(s, str):
        return s
    out = s
    for pat, full in _ADDR.items():
        out = re.sub(pat, full, out, flags=re.IGNORECASE)
    return out


CLEANERS = {
    "strip": c_strip, "lower": c_lower, "upper": c_upper,
    "collapse_ws": c_collapse_ws, "fix_mojibake": c_fix_mojibake,
    "ascii_fold": c_ascii_fold, "titlecase_smart": c_titlecase_smart,
    "expand_address_abbr": c_expand_address_abbr,
}


# ========================= helpers =========================
def is_empty(v):
    return v is None or (isinstance(v, float) and pd.isna(v)) or \
        (isinstance(v, str) and v.strip().lower() in EMPTY_TOKENS)


def map_alias(value, alias_dict):
    if is_empty(value):
        return None
    v = str(value).strip().lower().rstrip(".")
    for canon, variants in alias_dict.items():
        if v == canon.lower() or v in [x.lower() for x in variants]:
            return canon
    v2 = re.sub(r"[^a-z]", "", v)
    for canon, variants in alias_dict.items():
        if v2 in [re.sub(r"[^a-z]", "", x.lower()) for x in variants + [canon]]:
            return canon
    return None


def parse_amount(raw):
    if is_empty(raw):
        return None
    s = re.sub(r"[A-Za-z€£$₸]", "", str(raw)).strip()
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        if re.search(r",\d{2}$", s):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    s = s.replace(" ", "")
    try:
        return float(s)
    except ValueError:
        return None


def parse_date(raw, dayfirst):
    if is_empty(raw):
        return None
    try:
        d = dateparser.parse(str(raw), dayfirst=dayfirst, default=datetime(2000, 1, 1))
        return d.date()
    except (ValueError, OverflowError, TypeError):
        return None


def clean_phone(raw, region):
    if is_empty(raw):
        return None
    try:
        pn = phonenumbers.parse(str(raw), region)
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_possible_number(pn):
        return None
    nsn = str(pn.national_number)
    if len(set(nsn)) <= 1:          # reject bogus all-same-digit numbers e.g. (000) 000-0000
        return None
    return phonenumbers.format_number(pn, phonenumbers.PhoneNumberFormat.E164)


def valid_email(raw):
    if is_empty(raw):
        return None
    try:
        return validate_email(str(raw).strip(), check_deliverability=False).normalized.lower()
    except EmailNotValidError:
        return None


def split_name(raw):
    if is_empty(raw):
        return (None, None)
    s = c_collapse_ws(fix_text(str(raw)))
    if "," in s:                      # "Last, First"
        last, first = [p.strip() for p in s.split(",", 1)]
    else:
        toks = s.split()
        if len(toks) == 1:
            return (unidecode(toks[0]).title(), None)
        first, last = toks[0], toks[-1]
    first = unidecode(first).strip().title()
    last = unidecode(last).strip().rstrip(".").title()
    return (first or None, last or None)


# ========================= engine =========================
def clean_dataframe(df_raw, cfg):
    """Apply the YAML rules; return (clean_df, audit_df)."""
    fx = cfg["fx_to_usd"]
    country_aliases = cfg["country_aliases"]
    source_aliases = cfg["source_aliases"]
    region_cur = {"US": "USD", "GB": "GBP", "DE": "EUR", "FR": "EUR", "KZ": "KZT"}
    audit = []
    out = {c: [] for c in ["record_id", "first_name", "last_name", "email", "phone",
                           "company", "address", "city", "country", "postal_code",
                           "signup_date", "last_order_date", "order_count",
                           "total_spent_usd", "currency", "source"]}

    for _, row in df_raw.iterrows():
        rid = row["record_id"]

        def log(col, old, new, rule):
            ov = "" if is_empty(old) else str(old)[:60]
            nv = "" if new is None else str(new)[:60]
            if ov == nv:          # don't log no-op "changes" (e.g. an already-clean name)
                return
            audit.append({"record_id": rid, "column": col, "rule": rule,
                          "old_value": ov, "new_value": nv})

        country = map_alias(row.get("country"), country_aliases)
        if str(row.get("country")) != str(country):
            log("country", row.get("country"), country, "map_alias+validate")
        region = country if country in region_cur else "US"
        dayfirst = country in ("GB", "DE", "FR")

        first, last = split_name(row.get("name"))
        if first or last:
            log("name", row.get("name"), f"{first} {last}", "split_name+titlecase")

        email = valid_email(c_fix_mojibake(row.get("email")))
        if str(row.get("email")).strip().lower() != str(email or "").lower():
            log("email", row.get("email"), email, "validate_email+normalize")

        phone = clean_phone(row.get("phone"), region)
        if phone != row.get("phone"):
            log("phone", row.get("phone"), phone, "phone->E164")

        su = parse_date(row.get("signup_date"), dayfirst)
        if su and not (date(2015, 1, 1) <= su <= TODAY):
            su = None
        if str(row.get("signup_date")) != str(su or ""):
            log("signup_date", row.get("signup_date"), su, "parse_date+range")
        lo = parse_date(row.get("last_order_date"), dayfirst)
        if lo and not (date(2015, 1, 1) <= lo <= TODAY):
            lo = None

        local = parse_amount(row.get("total_spent"))
        cur = region_cur.get(country, "USD")
        usd = round(local * fx.get(cur, 1.0), 2) if local is not None and local >= 0 else None
        if usd is not None:
            log("total_spent", row.get("total_spent"), f"{usd} USD", "currency->USD")

        try:
            ocv = int(float(str(row.get("order_count"))))
            oc = ocv if 0 <= ocv <= 100000 else None
        except (ValueError, TypeError):
            oc = None

        company = c_titlecase_smart(c_collapse_ws(c_fix_mojibake(row.get("company"))))
        address = c_expand_address_abbr(c_collapse_ws(c_fix_mojibake(row.get("address"))))
        city_raw = c_collapse_ws(c_fix_mojibake(row.get("city")))
        if isinstance(city_raw, str) and "," in city_raw:
            city_raw = city_raw.split(",")[0].strip()
        city = c_titlecase_smart(unidecode(city_raw)) if isinstance(city_raw, str) else None
        source = map_alias(row.get("source"), source_aliases)
        postal = str(row.get("postal_code")).strip().upper() if not is_empty(row.get("postal_code")) else None

        out["record_id"].append(rid)
        out["first_name"].append(first)
        out["last_name"].append(last)
        out["email"].append(email)
        out["phone"].append(phone)
        out["company"].append(company or None)
        out["address"].append(address or None)
        out["city"].append(city or None)
        out["country"].append(country)
        out["postal_code"].append(postal)
        out["signup_date"].append(su.isoformat() if su else None)
        out["last_order_date"].append(lo.isoformat() if lo else None)
        out["order_count"].append(oc)
        out["total_spent_usd"].append(usd)
        out["currency"].append(cur if usd is not None else None)
        out["source"].append(source)

    clean = pd.DataFrame(out)
    audit_df = pd.DataFrame(audit, columns=["record_id", "column", "rule", "old_value", "new_value"])
    return clean, audit_df


def apply_quarantine(clean):
    """no_usable_identifier: no valid email AND no usable phone (or no name) -> quarantine."""
    has_id = clean["email"].notna() | clean["phone"].notna()
    has_name = clean["first_name"].notna() | clean["last_name"].notna()
    keep_mask = has_id & has_name
    q = clean[~keep_mask].copy()
    reasons = []
    for _, r in q.iterrows():
        why = []
        if pd.isna(r["email"]) and pd.isna(r["phone"]):
            why.append("no_usable_identifier (email & phone both invalid/missing)")
        if pd.isna(r["first_name"]) and pd.isna(r["last_name"]):
            why.append("no_name")
        reasons.append("; ".join(why) or "unusable_record")
    q["_reasons"] = reasons
    return clean[keep_mask].copy(), q


# ========================= dedup =========================
def _norm(s):
    return "" if s is None or (isinstance(s, float) and pd.isna(s)) else str(s)


def blocking_pairs(recs, cfg):
    keys = cfg["dedup"]["blocking_keys"]
    pairs = set()
    for key in keys:
        buckets = {}
        for i, r in recs.items():
            if key == "postal3_emailchar":
                k = _norm(r["postal_code"])[:3] + "|" + _norm(r["email"])[:1]
            elif key == "lastname_city":
                k = _norm(r["last_name"])[:4].lower() + "|" + _norm(r["city"])[:4].lower()
            elif key == "phone_tail":
                dig = re.sub(r"\D", "", _norm(r["phone"]))
                k = "ph:" + dig[-7:] if len(dig) >= 7 else ""
            else:
                k = ""
            if k and k.strip("|"):
                buckets.setdefault(k, []).append(i)
        for members in buckets.values():
            if len(members) < 2 or len(members) > 60:   # skip singletons & giant noise buckets
                continue
            m = sorted(members)
            for a in range(len(m)):
                for b in range(a + 1, len(m)):
                    pairs.add((m[a], m[b]))
    return pairs


def pair_score(r1, r2, cfg):
    w = cfg["dedup"]["weights"]
    name1 = f"{_norm(r1['first_name'])} {_norm(r1['last_name'])}".strip()
    name2 = f"{_norm(r2['first_name'])} {_norm(r2['last_name'])}".strip()
    fields = {
        "name": (name1, name2, fuzz.token_sort_ratio),
        "email": (_norm(r1["email"]), _norm(r2["email"]), fuzz.ratio),
        "phone": (_norm(r1["phone"]), _norm(r2["phone"]), fuzz.ratio),
        "address": (_norm(r1["address"]), _norm(r2["address"]), fuzz.token_set_ratio),
    }
    total_w, acc = 0.0, 0.0
    name_sim = fuzz.token_sort_ratio(name1, name2) if name1 and name2 else 0
    for f, (a, b, scorer) in fields.items():
        if a and b:
            acc += w[f] * scorer(a, b)
            total_w += w[f]
    if total_w == 0:
        return 0, name_sim
    return acc / total_w, name_sim


def dedup(df, cfg):
    thr = cfg["dedup"]["threshold"]
    recs = df.to_dict("index")
    pairs = blocking_pairs(recs, cfg)
    g = nx.Graph()
    g.add_nodes_from(df.index)
    matched = []
    for i, j in pairs:
        score, name_sim = pair_score(recs[i], recs[j], cfg)
        if score >= thr and name_sim >= 60:
            g.add_edge(i, j)
            matched.append((i, j, round(score, 1)))
    cid_of = {}
    for cid, comp in enumerate(nx.connected_components(g)):
        for node in comp:
            cid_of[node] = cid
    df = df.copy()
    df["cluster_id"] = [cid_of[i] for i in df.index]
    df["_complete"] = df.notna().sum(axis=1)
    df["_lo"] = pd.to_datetime(df["last_order_date"], errors="coerce")
    golden_idx = []
    for _, grp in df.groupby("cluster_id"):
        grp = grp.sort_values(["_complete", "_lo"], ascending=[False, False])
        golden_idx.append(grp.index[0])
    master = df.loc[golden_idx].drop(columns=["_complete", "_lo"]).reset_index(drop=True)
    return master, df[["record_id", "cluster_id"]].copy(), matched
