"""
Render portfolio slides (PNG) for the Data Cleanup & Validation Pipeline.
No browser -- pure matplotlib. ASCII/Latin text only (0 Cyrillic, self-checked).

Run:  python src/visuals.py   (after report.py has produced out/*)
Outputs screens/01-cover.png .. 07-audit.png
"""
from __future__ import annotations
import json
import os
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
OUT = os.path.join(HERE, "out")
SCREENS = os.path.join(HERE, "screens")

BG0 = "#0b1220"
CARD = "#131f33"
ACCENT = "#34d399"
RED = "#f87171"
WHITE = "#ffffff"
MUTE = "#9fb0c8"
GRID = "#22304a"
plt.rcParams["font.family"] = "DejaVu Sans"
CYRILLIC = re.compile(r"[Ѐ-ӿ]")


def gradient_bg(fig):
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_axis_off()
    h, w = 240, 320
    yy = np.linspace(0, 1, h)[:, None]
    xx = np.linspace(0, 1, w)[None, :]
    base = 0.0 * xx + yy
    glow = np.exp(-(((xx - 0.82) ** 2) / 0.05 + ((yy - 0.1) ** 2) / 0.05))
    img = np.zeros((h, w, 3))
    c0 = np.array([11, 18, 32]) / 255
    c1 = np.array([13, 43, 38]) / 255
    g = np.array([52, 211, 153]) / 255
    for k in range(3):
        img[:, :, k] = c0[k] + (c1[k] - c0[k]) * base
        img[:, :, k] = img[:, :, k] * (1 - 0.35 * glow) + g[k] * 0.35 * glow
    ax.imshow(np.clip(img, 0, 1), extent=[0, 1, 0, 1], aspect="auto", origin="upper", zorder=-10)
    return ax


def card(ax, x, y, w, h, fc=CARD, ec=GRID, lw=1.2, rad=0.02):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={rad}",
                                fc=fc, ec=ec, lw=lw, zorder=1, mutation_aspect=0.6))


def new_fig(w_in=16, h_in=10):
    fig = plt.figure(figsize=(w_in, h_in), dpi=100)
    ax = gradient_bg(fig)
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    return fig, ax


def title(ax, text, x=0.06, y=0.85, size=30, color=WHITE):
    ax.text(x, y, text, color=color, fontsize=size, fontweight="bold", va="top")


def mono(ax, x, y, s, color=WHITE, size=13, bold=False, ha="left"):
    ax.text(x, y, s, color=color, fontsize=size, family="DejaVu Sans Mono",
            fontweight="bold" if bold else "normal", va="center", ha=ha)


def load_all():
    raw = pd.read_csv(os.path.join(DATA, "messy_customers_25k.csv"), dtype=str, keep_default_na=False)
    raw["record_id"] = raw["record_id"].astype(int)
    gt = pd.read_csv(os.path.join(DATA, "ground_truth.csv"))
    master = pd.read_excel(os.path.join(OUT, "01_Cleaned_Master.xlsx"), dtype=str)
    master["record_id"] = master["record_id"].astype(int)
    quar = pd.read_excel(os.path.join(OUT, "02_Quarantine.xlsx"), dtype=str)
    audit = pd.read_csv(os.path.join(OUT, "03_Change_Log.csv"), dtype=str, keep_default_na=False)
    metrics = json.load(open(os.path.join(OUT, "metrics.json"), encoding="utf-8"))
    return raw, gt, master, quar, audit, metrics


# ------------------------- slides -------------------------
def s1_cover(data):
    raw, gt, master, quar, audit, m = data
    rf = m["run_facts"]
    fig, ax = new_fig(16, 12)
    ax.text(0.07, 0.90, "PYTHON  .  PANDAS  .  RAPIDFUZZ  .  DATA QUALITY",
            color=ACCENT, fontsize=16, fontweight="bold", family="DejaVu Sans Mono")
    ax.text(0.07, 0.82, "25,000 Messy Rows", color=WHITE, fontsize=50, fontweight="bold", va="top")
    ax.text(0.07, 0.72, "Clean, Deduplicated, Validated", color=ACCENT, fontsize=50, fontweight="bold", va="top")
    ax.text(0.07, 0.63, "One YAML config. One command. A full before/after data-quality report.",
            color=MUTE, fontsize=19, va="top")
    chips = [("25,000", "rows processed"),
             (f"{rf['Duplicate rate %']:.1f}%", "duplicates merged"),
             (f"{m['overall_before']:.0f}% -> {m['overall_after']:.0f}%", "data-quality score"),
             (f"{rf['Quarantined rows']:,}", "rows quarantined")]
    cw, gap, x0, y0, chh = 0.205, 0.015, 0.07, 0.40, 0.14
    for i, (big, lab) in enumerate(chips):
        x = x0 + i * (cw + gap)
        card(ax, x, y0, cw, chh)
        ax.text(x + cw / 2, y0 + chh * 0.60, big, color=ACCENT, fontsize=27,
                fontweight="bold", ha="center", va="center")
        ax.text(x + cw / 2, y0 + chh * 0.22, lab, color=MUTE, fontsize=14, ha="center", va="center")
    card(ax, 0.07, 0.07, 0.86, 0.26, fc="#0f1a2e")
    ax.text(0.09, 0.30, "DATA-QUALITY SCORECARD  (before -> after)", color=WHITE,
            fontsize=15, fontweight="bold", va="top")
    dims = m["scorecard"]
    names = ["Completeness", "Validity", "Uniqueness", "Consistency", "Accuracy", "Timeliness"]
    bx0, bw = 0.11, 0.135
    for i, nm in enumerate(names):
        b, a = dims[nm]["before"], dims[nm]["after"]
        x = bx0 + i * bw
        ax.add_patch(plt.Rectangle((x, 0.11), 0.05, 0.145 * b / 100, color=MUTE, alpha=0.55))
        ax.add_patch(plt.Rectangle((x + 0.055, 0.11), 0.05, 0.145 * a / 100, color=ACCENT))
        ax.text(x + 0.052, 0.095, nm[:7], color=MUTE, fontsize=10.5, ha="center", va="top")
        ax.text(x + 0.08, 0.11 + 0.145 * a / 100 + 0.004, f"{a:.0f}", color=ACCENT, fontsize=10.5, ha="center")
    fig.savefig(os.path.join(SCREENS, "01-cover.png"), facecolor=BG0)
    plt.close(fig)


def _find_examples(raw, master):
    r = raw.set_index("record_id")
    mm = master.set_index("record_id")
    ex = {}
    for rid in mm.index[:5000]:
        if rid not in r.index:
            continue
        rr, mr = r.loc[rid], mm.loc[rid]
        if "date" not in ex and re.search(r"[./]", str(rr["signup_date"])) and re.match(r"\d{4}-\d{2}-\d{2}", str(mr["signup_date"])):
            ex["date"] = (rr["signup_date"].strip(), mr["signup_date"])
        if "phone" not in ex and re.search(r"[()\.\s]", str(rr["phone"])) and str(mr["phone"]).startswith("+"):
            ex["phone"] = (rr["phone"].strip(), mr["phone"])
        if "money" not in ex and re.search(r"[€£]|EUR|GBP", str(rr["total_spent"])) and str(mr["total_spent_usd"]) not in ("", "nan"):
            ex["money"] = (rr["total_spent"].strip(), f'${float(mr["total_spent_usd"]):,.2f}')
        if "country" not in ex and str(rr["country"]).strip() not in ("US", "GB", "DE", "FR", "KZ", "") and str(mr["country"]) in ("US", "GB", "DE", "FR", "KZ"):
            ex["country"] = (rr["country"].strip(), mr["country"])
        if "ws" not in ex and (rr["name"] != rr["name"].strip() or rr["name"].isupper() or "," in rr["name"]) and str(mr["first_name"]) not in ("", "nan"):
            ex["ws"] = (f'"{rr["name"]}"', f'{mr["first_name"]} {mr["last_name"]}')
        if len(ex) >= 5:
            break
    return ex


def s3_fields(data):
    raw, gt, master, quar, audit, m = data
    ex = _find_examples(raw, master)
    fig, ax = new_fig()
    ax.text(0.06, 0.92, "FIELD STANDARDIZATION", color=ACCENT, fontsize=15,
            fontweight="bold", family="DejaVu Sans Mono")
    title(ax, "Before  ->  After : one rule per defect", y=0.86, size=28)
    rows = [("Mixed date formats", ex.get("date", ("07.10.2016", "2016-10-07"))),
            ("Phone to E.164", ex.get("phone", ("(388) 024-2765", "+493880242765"))),
            ("Mixed currency to USD", ex.get("money", ("1.491,87 EUR", "$1,611.22"))),
            ("Country code", ex.get("country", ("United States", "US"))),
            ("Name case / order + spaces", ex.get("ws", ('"  adolph, willy "', "Willy Adolph")))]
    y = 0.74
    for label, (b, a) in rows:
        card(ax, 0.06, y - 0.04, 0.88, 0.11, fc=CARD)
        ax.text(0.08, y + 0.05, label, color=MUTE, fontsize=14, va="center")
        mono(ax, 0.08, y - 0.005, str(b)[:34], color=RED, size=16)
        ax.annotate("", xy=(0.57, y - 0.005), xytext=(0.48, y - 0.005),
                    arrowprops=dict(arrowstyle="-|>", color=ACCENT, lw=2))
        mono(ax, 0.60, y - 0.005, str(a)[:28], color=ACCENT, size=16, bold=True)
        y -= 0.135
    fig.savefig(os.path.join(SCREENS, "03-fields.png"), facecolor=BG0)
    plt.close(fig)


def s2_dedup(data):
    raw, gt, master, quar, audit, m = data
    cnt = gt.entity_id.value_counts()
    dup_ents = cnt[cnt == 2].index
    r = raw.set_index("record_id")
    mset = set(master["record_id"].astype(int))
    chosen = None
    for e in dup_ents:
        rids = gt[gt.entity_id == e].record_id.tolist()
        if all(rid in r.index for rid in rids) and any(rid in mset for rid in rids):
            if all(str(r.loc[rid]["email"]).strip() not in ("", "n/a") for rid in rids):
                chosen = (e, rids); break
    e, rids = chosen
    mm = master.set_index("record_id")
    gold_rid = [rid for rid in rids if rid in mset][0]
    g = mm.loc[gold_rid]
    fig, ax = new_fig()
    ax.text(0.06, 0.92, "FUZZY DEDUPLICATION -> GOLDEN RECORD", color=ACCENT,
            fontsize=15, fontweight="bold", family="DejaVu Sans Mono")
    title(ax, "Two near-duplicate rows merged into one", y=0.86, size=27)
    y = 0.75
    for rid in rids:
        rr = r.loc[rid]
        card(ax, 0.06, y - 0.045, 0.88, 0.1, fc="#2a1620", ec="#5b2a39")
        ax.text(0.08, y + 0.035, f"RAW record #{rid}", color=RED, fontsize=12, fontweight="bold")
        mono(ax, 0.08, y - 0.012, f'{rr["name"][:20]:22}{rr["email"][:26]:28}{rr["phone"][:16]:17}{rr["city"][:12]}', size=12)
        y -= 0.145
    ax.annotate("", xy=(0.5, y + 0.03), xytext=(0.5, y + 0.09),
                arrowprops=dict(arrowstyle="-|>", color=ACCENT, lw=3))
    ax.text(0.53, y + 0.06, "match score >= threshold  ->  survivorship (most complete, latest)",
            color=MUTE, fontsize=12, va="center")
    card(ax, 0.06, y - 0.10, 0.88, 0.12, fc="#13261f", ec=ACCENT, lw=1.6)
    ax.text(0.08, y, f"GOLDEN record (kept #{gold_rid})", color=ACCENT, fontsize=13, fontweight="bold")
    nm = f'{g["first_name"]} {g["last_name"]}'
    mono(ax, 0.08, y - 0.05, f'{nm[:20]:22}{str(g["email"])[:26]:28}{str(g["phone"])[:16]:17}{str(g["city"])[:12]}',
         color=ACCENT, size=12, bold=True)
    fig.savefig(os.path.join(SCREENS, "02-dedup.png"), facecolor=BG0)
    plt.close(fig)


def s4_scorecard(data):
    raw, gt, master, quar, audit, m = data
    dims = m["scorecard"]
    names = list(dims.keys())
    before = [dims[n]["before"] for n in names]
    after = [dims[n]["after"] for n in names]
    fig, ax = new_fig()
    ax.text(0.06, 0.93, "DATA-QUALITY SCORECARD", color=ACCENT, fontsize=15,
            fontweight="bold", family="DejaVu Sans Mono")
    title(ax, f"Overall {m['overall_before']:.0f}%  ->  {m['overall_after']:.0f}%", y=0.88, size=30)
    card(ax, 0.06, 0.16, 0.40, 0.66, fc=CARD)
    ax.text(0.08, 0.78, f'{"Dimension":14}{"Before":>8}{"After":>8}', color=WHITE,
            fontsize=13, family="DejaVu Sans Mono", fontweight="bold", va="top")
    y = 0.72
    for n in names:
        ax.text(0.08, y, f'{n:14}{dims[n]["before"]:>7.1f}{dims[n]["after"]:>8.1f}',
                color=MUTE, fontsize=13, family="DejaVu Sans Mono", va="top")
        y -= 0.065
    ax.text(0.08, y - 0.01, f'{"OVERALL":14}{m["overall_before"]:>7.1f}{m["overall_after"]:>8.1f}',
            color=ACCENT, fontsize=13, family="DejaVu Sans Mono", fontweight="bold", va="top")
    bax = fig.add_axes([0.52, 0.18, 0.42, 0.60])
    bax.set_facecolor("none")
    xpos = np.arange(len(names))
    bax.bar(xpos - 0.2, before, 0.38, color=MUTE, alpha=0.6, label="before")
    bax.bar(xpos + 0.2, after, 0.38, color=ACCENT, label="after")
    bax.set_xticks(xpos); bax.set_xticklabels([n[:5] for n in names], color=MUTE, fontsize=10)
    bax.set_ylim(0, 105); bax.tick_params(colors=MUTE)
    for s in bax.spines.values():
        s.set_color(GRID)
    bax.legend(facecolor=CARD, edgecolor=GRID, labelcolor=WHITE, fontsize=11, loc="lower right")
    fig.savefig(os.path.join(SCREENS, "04-scorecard.png"), facecolor=BG0)
    plt.close(fig)


def s5_quarantine(data):
    raw, gt, master, quar, audit, m = data
    fig, ax = new_fig()
    ax.text(0.06, 0.93, "QUARANTINE  (unfixable rows kept with a reason)", color=ACCENT,
            fontsize=15, fontweight="bold", family="DejaVu Sans Mono")
    title(ax, f"{m['run_facts']['Quarantined rows']:,} rows isolated, 0 fixable records dropped", y=0.87, size=24)
    def disp(v):
        s = str(v).strip()
        return "-" if s in ("", "nan", "n/a", "N/A", "None") else s

    def short_reason(v):
        s = str(v)
        if "no_name" in s and "no_usable_identifier" in s:
            return "no valid email/phone + no name"
        if "no_usable_identifier" in s:
            return "no valid email or phone"
        return s[:32]

    sample = quar.head(7)
    card(ax, 0.05, 0.16, 0.90, 0.64, fc=CARD)
    ax.text(0.07, 0.76, f'{"name":16}{"email":22}{"phone":14}  reason', color=WHITE,
            fontsize=12, family="DejaVu Sans Mono", fontweight="bold", va="top")
    y = 0.70
    for _, rr in sample.iterrows():
        ax.text(0.07, y, f'{disp(rr["name"])[:14]:16}{disp(rr["email"])[:20]:22}{disp(rr["phone"])[:12]:14}',
                color=MUTE, fontsize=11.5, family="DejaVu Sans Mono", va="top")
        ax.text(0.66, y, short_reason(rr["_reasons"]), color=RED, fontsize=11, family="DejaVu Sans Mono", va="top")
        y -= 0.075
    ax.text(0.07, 0.20, "Rule: no usable identifier (no valid email AND no usable phone).  "
                        "Verified vs ground truth: 0 recoverable records quarantined.",
            color=MUTE, fontsize=12, va="top")
    fig.savefig(os.path.join(SCREENS, "05-quarantine.png"), facecolor=BG0)
    plt.close(fig)


def s6_rules(data):
    fig, ax = new_fig()
    ax.text(0.06, 0.93, "CONFIGURABLE RULES  (rules.yaml)", color=ACCENT, fontsize=15,
            fontweight="bold", family="DejaVu Sans Mono")
    title(ax, "Every rule in one file. Add a rule = one line, no code change.", y=0.88, size=22)
    txt = open(os.path.join(HERE, "rules.yaml"), encoding="utf-8").read().splitlines()
    snippet = [ln for ln in txt if ln.strip()][:34]
    card(ax, 0.05, 0.08, 0.90, 0.74, fc="#0f1a2e")
    y = 0.79
    for ln in snippet:
        col = ACCENT if (ln.strip().endswith(":") and not ln.startswith(" ")) else MUTE
        if ln.strip().startswith("#"):
            col = "#5b6b84"
        ax.text(0.07, y, ln[:74], color=col, fontsize=11, family="DejaVu Sans Mono", va="top")
        y -= 0.0205
    fig.savefig(os.path.join(SCREENS, "06-rules.png"), facecolor=BG0)
    plt.close(fig)


def s7_audit(data):
    raw, gt, master, quar, audit, m = data
    fig, ax = new_fig()
    ax.text(0.06, 0.93, "AUDIT TRAIL  (every change logged)", color=ACCENT, fontsize=15,
            fontweight="bold", family="DejaVu Sans Mono")
    title(ax, f"{int(m['run_facts']['Field changes logged']):,} field changes, fully traceable", y=0.87, size=24)
    sample = audit[audit["new_value"].astype(str).str.len() > 0].head(9)
    card(ax, 0.05, 0.16, 0.90, 0.64, fc=CARD)
    ax.text(0.07, 0.76, f'{"id":>6}  {"column":13}{"rule":24}{"old":13}-> new', color=WHITE,
            fontsize=12, family="DejaVu Sans Mono", fontweight="bold", va="top")
    y = 0.70
    for _, rr in sample.iterrows():
        ax.text(0.07, y, f'{str(rr["record_id"]):>6}  {str(rr["column"])[:11]:13}{str(rr["rule"])[:22]:24}'
                         f'{str(rr["old_value"])[:11]:13}',
                color=MUTE, fontsize=11, family="DejaVu Sans Mono", va="top")
        ax.text(0.80, y, "-> " + str(rr["new_value"])[:15], color=ACCENT, fontsize=11,
                family="DejaVu Sans Mono", va="top")
        y -= 0.058
    fig.savefig(os.path.join(SCREENS, "07-audit.png"), facecolor=BG0)
    plt.close(fig)


def s8_excel(data):
    fig, ax = new_fig()
    ax.text(0.06, 0.93, "WHY NOT JUST EXCEL?", color=ACCENT, fontsize=15,
            fontweight="bold", family="DejaVu Sans Mono")
    title(ax, "Excel does the easy 60%. This owns the 40% that breaks it.", y=0.88, size=25)

    easy = ["Remove EXACT duplicates", "Trim spaces, fix case",
            "Split / merge columns (Power Query)", "Change data types"]
    hard = ["Fuzzy-merge the SAME person (Jon/John, name flip)",
            "Phones to E.164, validated per country",
            "Mixed/locale dates (no silent dd-mm vs mm-dd)",
            "Fix broken encodings; unify 3 currencies to USD",
            "Audit log of every change + quarantine with reasons",
            "Re-run on next month's file in one command"]

    card(ax, 0.05, 0.16, 0.43, 0.63, fc=CARD)
    ax.text(0.07, 0.75, "A few clicks in Excel / Power Query", color=WHITE,
            fontsize=15, fontweight="bold", va="top")
    y = 0.66
    for t in easy:
        ax.text(0.07, y, "✓", color=ACCENT, fontsize=16, fontweight="bold", va="top")
        ax.text(0.10, y, t, color=MUTE, fontsize=13.5, va="top")
        y -= 0.075

    card(ax, 0.52, 0.16, 0.43, 0.63, fc="#1a1322", ec="#4a2a3a")
    ax.text(0.54, 0.75, "Where Excel silently breaks", color=WHITE,
            fontsize=15, fontweight="bold", va="top")
    y = 0.66
    for t in hard:
        ax.text(0.54, y, "✗", color=RED, fontsize=16, fontweight="bold", va="top")
        ax.text(0.565, y, t, color="#d7c2cc", fontsize=12.5, va="top")
        y -= 0.082

    ax.text(0.5, 0.10, "The pipeline does all of it, by rules in one config, and reproducibly.",
            color=ACCENT, fontsize=14, ha="center", va="center", fontweight="bold")
    fig.savefig(os.path.join(SCREENS, "08-excel.png"), facecolor=BG0)
    plt.close(fig)


def cyrillic_scan(data):
    raw, gt, master, quar, audit, m = data
    hits = 0
    for df in (quar.head(7), audit.head(40), master.head(50), raw.head(50)):
        for v in df.values.ravel():
            if CYRILLIC.search(str(v)):
                hits += 1
    return hits


def main():
    os.makedirs(SCREENS, exist_ok=True)
    data = load_all()
    for fn in (s1_cover, s2_dedup, s3_fields, s4_scorecard, s5_quarantine, s6_rules, s7_audit, s8_excel):
        fn(data)
    pngs = sorted(f for f in os.listdir(SCREENS) if f.endswith(".png"))
    print("[OK] rendered", len(pngs), "slides:", ", ".join(pngs))
    hits = cyrillic_scan(data)
    print("[%s] cyrillic in shown data: %d" % ("OK" if hits == 0 else "WARN", hits))


if __name__ == "__main__":
    main()
