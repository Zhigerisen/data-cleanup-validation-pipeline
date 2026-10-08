"""
Generate a realistic *dirty* customer/CRM export (25,000 rows) for the
Data Cleanup & Validation Pipeline demo.

100% synthetic (Faker, fixed seed). No real people, no real PII.
Outputs:
  data/messy_customers_25k.csv  -- the dirty input
  data/ground_truth.csv         -- true entity_id per record (for honest metrics)
  data/clean_reference.csv      -- canonical values per entity (for Accuracy scoring)

ASCII-only console output (Windows cp1251 safe).
"""
from __future__ import annotations
import csv
import os
import random
from datetime import date, timedelta

import phonenumbers
from faker import Faker

SEED = 42
N_ENTITIES = 20000
N_NEAR_DUP = 4500
N_EXACT_DUP = 500            # total rows = 25,000
N_UNFIXABLE = 380            # ~1.5% rows with no usable identifier (quarantine truth)

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")

# region -> (faker locale, currency, fx_to_usd)
COUNTRIES = {
    "US": ("en_US", "USD", 1.0),
    "GB": ("en_GB", "GBP", 1.27),
    "DE": ("de_DE", "EUR", 1.08),
    "FR": ("fr_FR", "EUR", 1.08),
    "KZ": ("en_US", "KZT", 0.0021),   # en_US names kept ASCII; KZ cities below
}
COUNTRY_WEIGHTS = [("US", 0.42), ("GB", 0.20), ("DE", 0.16), ("FR", 0.14), ("KZ", 0.08)]
KZ_CITIES = ["Almaty", "Astana", "Shymkent", "Karaganda", "Aktobe", "Taraz"]
PROVIDERS = ["gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com", "proton.me"]
SOURCES_CANON = {
    "Facebook": ["fb", "Facebook", "FB Ads", "facebook ads", "Meta"],
    "Google": ["google", "Google Ads", "adwords", "GGL", "goog"],
    "Organic": ["organic", "SEO", "direct", "Website"],
    "Referral": ["referral", "ref", "word of mouth", "Friend"],
    "Email": ["email", "Newsletter", "mailing"],
}
COUNTRY_MESSY = {
    "US": ["US", "USA", "United States", "u.s.", "America"],
    "GB": ["UK", "United Kingdom", "gb", "England", "Great Britain"],
    "DE": ["Germany", "DE", "Deutschland", "GER"],
    "FR": ["France", "FR", "fra"],
    "KZ": ["Kazakhstan", "KZ", "kaz", "Qazaqstan"],
}

rng = random.Random(SEED)
Faker.seed(SEED)
fakers = {loc: Faker(loc) for loc in {c[0] for c in COUNTRIES.values()}}
for f in fakers.values():
    f.seed_instance(SEED)

# precompute an example national number per region (length + leading digit)
EX_NSN = {r: str(phonenumbers.example_number(r).national_number) for r in COUNTRIES}
CC = {r: phonenumbers.country_code_for_region(r) for r in COUNTRIES}


def weighted_country() -> str:
    x = rng.random()
    acc = 0.0
    for c, w in COUNTRY_WEIGHTS:
        acc += w
        if x <= acc:
            return c
    return "US"


def gen_phone(region: str):
    """Return (national_digits, e164) that is 'possible' per phonenumbers."""
    nsn = EX_NSN[region]
    for _ in range(12):
        digits = nsn[0] + "".join(rng.choice("0123456789") for _ in range(len(nsn) - 1))
        e164 = f"+{CC[region]}{digits}"
        try:
            pn = phonenumbers.parse(e164, None)
            if phonenumbers.is_possible_number(pn):
                return digits, e164
        except phonenumbers.NumberParseException:
            pass
    return digits, e164


def _ascii(s: str) -> str:
    from unidecode import unidecode
    return unidecode(s)


def gen_entity(eid: int) -> dict:
    country = weighted_country()
    loc, currency, rate = COUNTRIES[country]
    fk = fakers[loc]
    first = fk.first_name()
    last = fk.last_name()
    digits, e164 = gen_phone(country)
    base_usd = round(rng.uniform(15, 6000), 2)
    local_amount = round(base_usd / rate, 2)
    signup = date(2015, 1, 1) + timedelta(days=rng.randint(0, 4200))
    last_order = signup + timedelta(days=rng.randint(0, 1500))
    if last_order > date(2026, 9, 30):
        last_order = date(2026, 9, 30)
    city = rng.choice(KZ_CITIES) if country == "KZ" else fk.city()
    company = "" if rng.random() < 0.45 else fk.company()
    source = rng.choice(list(SOURCES_CANON))
    local_part = f"{_ascii(first).lower()}.{_ascii(last).lower()}"
    if rng.random() < 0.4:
        local_part += str(rng.randint(1, 999))
    email = f"{local_part}@{rng.choice(PROVIDERS)}"
    postal = "".join(rng.choice("0123456789") for _ in range(5))
    street = fk.street_address().replace("\n", " ")
    return {
        "entity_id": eid, "country": country, "currency": currency, "rate": rate,
        "first": first, "last": last, "phone_digits": digits, "phone_e164": e164,
        "base_usd": base_usd, "local_amount": local_amount, "signup": signup,
        "last_order": last_order, "city": city, "company": company, "source": source,
        "email": email, "postal": postal, "street": street,
        "order_count": rng.randint(1, 240),
    }


# ----------------------- messy string renderers -----------------------
def mojibake(s: str) -> str:
    try:
        return s.encode("utf-8").decode("latin-1")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def mess_case_ws(s: str) -> str:
    r = rng.random()
    if r < 0.25:
        s = s.upper()
    elif r < 0.45:
        s = s.lower()
    if rng.random() < 0.3:
        s = "  " + s
    if rng.random() < 0.3:
        s = s + "   "
    if rng.random() < 0.2:
        s = s.replace(" ", "  ", 1)
    if rng.random() < 0.1:
        s = s + " "   # trailing non-breaking space
    return s


def messy_name(first: str, last: str) -> str:
    style = rng.random()
    if style < 0.2:
        name = f"{last}, {first}"       # reversed
    elif style < 0.3:
        name = f"{first} {last[0]}."    # initial
    else:
        name = f"{first} {last}"
    if rng.random() < 0.3:
        name = mess_case_ws(name)
    if rng.random() < 0.08:
        name = mojibake(name)
    return name


def messy_email(email: str, broken: bool = False) -> str:
    if broken:
        kind = rng.random()
        if kind < 0.3:
            return email.replace("@", " ")
        if kind < 0.5:
            return email.replace("@", "")
        if kind < 0.7:
            return "test@test"
        if kind < 0.85:
            return email.replace(".", "..", 1)
        return email.replace("@", "@@")
    e = email
    if rng.random() < 0.3:
        e = e.upper()
    if rng.random() < 0.2:
        e = " " + e + " "
    return e


def messy_phone(digits: str, region: str, broken: bool = False) -> str:
    if broken:
        kind = rng.random()
        if kind < 0.4:
            return digits[:4] + "ABC"
        if kind < 0.7:
            return "(000) 000-0000"
        return digits[:5]
    r = rng.random()
    if r < 0.3:
        return f"+{CC[region]} {digits[:3]} {digits[3:6]} {digits[6:]}"
    if r < 0.55:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    if r < 0.75:
        return f"0{digits}" if region != "US" else digits   # trunk '0' only where it exists
    if r < 0.9:
        return ".".join([digits[:3], digits[3:6], digits[6:]])
    return digits


def messy_date(d: date, country: str, broken: bool = False) -> str:
    if broken:
        kind = rng.random()
        if kind < 0.4:
            return "13/32/2026"
        if kind < 0.7:
            return rng.choice(["yesterday", "N/A", "-", "TBD"])
        return "00/00/0000"
    dayfirst = country in ("GB", "DE", "FR")
    fmts = (["%d/%m/%Y", "%d.%m.%Y"] if dayfirst else ["%m/%d/%Y"]) + \
        ["%Y-%m-%d", "%b %d %Y", "%d %b %Y"]
    return d.strftime(rng.choice(fmts))


def messy_amount(local_amount: float, country: str) -> str:
    cur = COUNTRIES[country][1]
    if country in ("DE", "FR"):            # 1.234,50 style
        s = f"{local_amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return rng.choice([f"{s} EUR", f"{s} €", s])
    if country == "KZ":
        s = f"{local_amount:,.0f}".replace(",", " ")
        return rng.choice([f"{s} KZT", f"{s} ₸", s])
    sym = "$" if country == "US" else "£"
    s = f"{local_amount:,.2f}"
    return rng.choice([f"{sym}{s}", f"{cur} {s}", s])


def messy_country(country: str) -> str:
    return rng.choice(COUNTRY_MESSY[country])


def messy_source(canon: str) -> str:
    return rng.choice(SOURCES_CANON[canon])


def messy_city(city: str) -> str:
    c = city
    if rng.random() < 0.3:
        c = mess_case_ws(c)
    if rng.random() < 0.12:
        c = mojibake(c)
    return c


def render_row(ent: dict, broken_email=None, broken_phone=None) -> dict:
    """Turn a canonical entity into one messy CSV row (dict of strings)."""
    be = rng.random() < 0.08 if broken_email is None else broken_email
    bp = rng.random() < 0.12 if broken_phone is None else broken_phone
    bd = rng.random() < 0.18
    addr = ent["street"]
    if rng.random() < 0.3:
        addr = addr.replace("Street", "St.").replace("Avenue", "Ave").replace("Road", "Rd")
    city_field = messy_city(ent["city"])
    if rng.random() < 0.08:    # column-merge defect: city + country glued together
        city_field = f"{ent['city']}, {messy_country(ent['country'])}"
    comp = ent["company"]
    if comp and rng.random() < 0.1:
        comp = mojibake(mess_case_ws(comp))
    return {
        "name": messy_name(ent["first"], ent["last"]),
        "email": "" if (be and rng.random() < 0.15) else messy_email(ent["email"], be),
        "phone": "" if (bp and rng.random() < 0.2) else messy_phone(ent["phone_digits"], ent["country"], bp),
        "company": comp,
        "address": mess_case_ws(addr) if rng.random() < 0.2 else addr,
        "city": city_field,
        "country": "" if rng.random() < 0.04 else messy_country(ent["country"]),
        "postal_code": ent["postal"],
        "signup_date": messy_date(ent["signup"], ent["country"], bd and rng.random() < 0.5),
        "last_order_date": "" if rng.random() < 0.06 else messy_date(ent["last_order"], ent["country"], bd and rng.random() < 0.3),
        "order_count": str(ent["order_count"]) if rng.random() < 0.95 else rng.choice(["", "N/A", "-1"]),
        "total_spent": messy_amount(ent["local_amount"], ent["country"]),
        "source": messy_source(ent["source"]),
    }


def mutate_for_near_dup(ent: dict) -> dict:
    """Clone an entity with light real-world variations (same real person)."""
    e = dict(ent)
    f = ent["first"]
    if rng.random() < 0.5 and len(f) > 3:
        e["first"] = f[:-1]                      # drop last letter (typo)
    if rng.random() < 0.45:                      # vary email in ~45% of near-dups
        base = ent["email"].split("@")[0]
        if rng.random() < 0.5 and len(base) > 2:
            base = base[:-1]
        e["email"] = f"{base}@{rng.choice(PROVIDERS)}"
    # phone digits identical (anchor); render_row reformats it
    return e


def main() -> None:
    os.makedirs(DATA, exist_ok=True)
    print("[..] generating", N_ENTITIES, "entities")
    entities = [gen_entity(i) for i in range(N_ENTITIES)]

    rows = []
    references = []

    dup_pool = rng.sample(range(N_ENTITIES), N_NEAR_DUP + N_EXACT_DUP)
    near_ids = set(dup_pool[:N_NEAR_DUP])
    exact_ids = set(dup_pool[N_NEAR_DUP:])
    singletons = [i for i in range(N_ENTITIES) if i not in near_ids and i not in exact_ids]
    unfixable_ids = set(rng.sample(singletons, N_UNFIXABLE))

    for ent in entities:
        eid = ent["entity_id"]
        references.append({
            "entity_id": eid,
            "first_name": _ascii(ent["first"]).title(),
            "last_name": _ascii(ent["last"]).title(),
            "email_canon": ent["email"].lower(),
            "phone_e164": ent["phone_e164"],
            "city_canon": _ascii(ent["city"]).title(),
            "country_code": ent["country"],
            "total_spent_usd": round(ent["base_usd"], 2),
        })
        if eid in unfixable_ids:
            row = render_row(ent, broken_email=True, broken_phone=True)
            row["email"] = rng.choice(["", "test@test", "n/a", "notanemail", "???"])
            row["phone"] = rng.choice(["", "N/A", "n/a", "invalid", "---", "call me"])
            rows.append(({"entity_id": eid, "dup_type": "unique", "quarantine_truth": 1}, row))
            continue
        base_row = render_row(ent)
        rows.append(({"entity_id": eid, "dup_type": "unique", "quarantine_truth": 0}, base_row))
        if eid in near_ids:
            rows.append(({"entity_id": eid, "dup_type": "near", "quarantine_truth": 0},
                         render_row(mutate_for_near_dup(ent))))
        if eid in exact_ids:
            rows.append(({"entity_id": eid, "dup_type": "exact", "quarantine_truth": 0},
                         dict(base_row)))

    rng.shuffle(rows)

    cols = ["record_id", "name", "email", "phone", "company", "address", "city",
            "country", "postal_code", "signup_date", "last_order_date",
            "order_count", "total_spent", "source"]
    msgpath = os.path.join(DATA, "messy_customers_25k.csv")
    gtpath = os.path.join(DATA, "ground_truth.csv")
    with open(msgpath, "w", newline="", encoding="utf-8") as fm, \
            open(gtpath, "w", newline="", encoding="utf-8") as fg:
        wm = csv.DictWriter(fm, fieldnames=cols)
        wm.writeheader()
        wg = csv.DictWriter(fg, fieldnames=["record_id", "entity_id", "dup_type", "quarantine_truth"])
        wg.writeheader()
        for rid, (meta, row) in enumerate(rows, start=1):
            out = {"record_id": rid}
            out.update(row)
            wm.writerow(out)
            wg.writerow({"record_id": rid, "entity_id": meta["entity_id"],
                         "dup_type": meta["dup_type"], "quarantine_truth": meta["quarantine_truth"]})

    refpath = os.path.join(DATA, "clean_reference.csv")
    with open(refpath, "w", newline="", encoding="utf-8") as fr:
        wr = csv.DictWriter(fr, fieldnames=list(references[0].keys()))
        wr.writeheader()
        wr.writerows(references)

    n = len(rows)
    n_exact = sum(1 for m, _ in rows if m["dup_type"] == "exact")
    n_near = sum(1 for m, _ in rows if m["dup_type"] == "near")
    n_q = sum(m["quarantine_truth"] for m, _ in rows)
    print("[OK] rows total        :", n)
    print("[OK] unique entities   :", N_ENTITIES)
    print("[OK] near-dup rows      :", n_near)
    print("[OK] exact-dup rows     :", n_exact)
    print("[OK] true dup pairs     :", n_near + n_exact)
    print("[OK] unfixable (quar.)  :", n_q, "(%.1f%%)" % (100.0 * n_q / n))
    print("[OK] wrote:", msgpath)
    print("[OK] wrote:", gtpath)
    print("[OK] wrote:", refpath)


if __name__ == "__main__":
    main()
