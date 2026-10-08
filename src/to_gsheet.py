"""
Publish the pipeline results into a Google Sheet (demo exhibit for the portfolio card).

The service account cannot CREATE files (0 GB Drive quota), so the founder creates an
empty spreadsheet, shares it with the service account as Editor, and passes the URL:

    python src/to_gsheet.py "<spreadsheet url or id>"

Tabs produced: READ ME / Quality Scorecard / BEFORE / AFTER / Quarantine / Change log.
ASCII-only console output.
"""
from __future__ import annotations
import json
import os
import sys

import gspread
import pandas as pd
from google.oauth2.service_account import Credentials

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "out")
DATA = os.path.join(HERE, "data")
CREDS = r"C:\Users\zhiga\.claude\google-credentials.json"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets",
          "https://www.googleapis.com/auth/drive"]
REPO = "https://github.com/Zhigerisen/data-cleanup-validation-pipeline"
SAMPLE = 200
LOG_SAMPLE = 500


def frame_to_values(df, numeric=()):
    """Header + rows. Values stay literal (sent with RAW) so that a phone like
    '+77755951212' is not swallowed as a formula; listed columns become real numbers."""
    df = df.fillna("")
    cols = list(df.columns)
    rows = [cols]
    for rec in df.astype(object).values.tolist():
        row = []
        for c, v in zip(cols, rec):
            if c in numeric and v != "":
                try:
                    v = float(v)
                except (TypeError, ValueError):
                    pass
            row.append(v)
        rows.append(row)
    return rows


def put(sh, title, values, rows=None, cols=None, vio="USER_ENTERED"):
    try:
        ws = sh.worksheet(title)
        ws.clear()
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=title,
                              rows=rows or max(len(values) + 10, 50),
                              cols=cols or max(len(values[0]) + 2, 10))
    ws.update(range_name="A1", values=values, value_input_option=vio)
    ws.freeze(rows=1)
    ws.format("1:1", {"textFormat": {"bold": True}})
    print("[OK] tab:", title, "rows:", len(values))
    return ws


def finalize(sh):
    """English locale (so amounts render as 1,234.56) + currency format on the USD column."""
    sh.batch_update({"requests": [{"updateSpreadsheetProperties": {
        "properties": {"locale": "en_US", "timeZone": "Etc/GMT"},
        "fields": "locale,timeZone"}}]})
    ws = sh.worksheet("AFTER (clean master)")
    col = ws.row_values(1).index("total_spent_usd")
    sh.batch_update({"requests": [{"repeatCell": {
        "range": {"sheetId": ws.id, "startRowIndex": 1,
                  "startColumnIndex": col, "endColumnIndex": col + 1},
        "cell": {"userEnteredFormat": {"numberFormat": {"type": "CURRENCY",
                                                        "pattern": "$#,##0.00"}}},
        "fields": "userEnteredFormat.numberFormat"}}]})
    print("[OK] locale en_US + currency format applied")


def main(url):
    creds = Credentials.from_service_account_file(CREDS, scopes=SCOPES)
    gc = gspread.authorize(creds)
    sh = gc.open_by_url(url) if url.startswith("http") else gc.open_by_key(url)
    print("[..] opened:", sh.title)

    m = json.load(open(os.path.join(OUT, "metrics.json"), encoding="utf-8"))
    rf, sc = m["run_facts"], m["scorecard"]

    # ---- READ ME ----
    readme = [
        ["Data Cleanup & Validation Pipeline - live demo"],
        [],
        ["What this is", "25,000 rows of realistically messy customer data cleaned, validated and"],
        ["", "deduplicated by a configurable Python pipeline. Rules live in one YAML file."],
        ["Data", "100% SYNTHETIC (Faker, fixed seed). No real people, no real PII."],
        ["Source code", REPO],
        [],
        ["Headline results", ""],
        ["Input rows", rf["Input rows"]],
        ["Clean golden records", rf["Clean golden records"]],
        ["Duplicate rows merged", rf["Duplicate rows merged"]],
        ["Duplicate rate %", rf["Duplicate rate %"]],
        ["Rows quarantined", rf["Quarantined rows"]],
        ["Fixable records dropped", rf["Quarantine false-drops"]],
        ["Field changes logged", rf["Field changes logged"]],
        ["Dedup precision %", rf["Dedup precision %"]],
        ["Dedup recall %", rf["Dedup recall %"]],
        ["Overall data quality", f'{m["overall_before"]}% -> {m["overall_after"]}%'],
        ["Runtime (sec)", rf["Runtime sec"]],
        [],
        ["Tabs", "Quality Scorecard | BEFORE (messy input) | AFTER (clean master) | Quarantine | Change log"],
        ["Note", "BEFORE and AFTER show the SAME records, so you can compare row by row."],
    ]
    put(sh, "READ ME", readme)

    # ---- Scorecard ----
    dims = [["Dimension", "Before %", "After %", "Delta (pp)"]]
    for d, v in sc.items():
        dims.append([d, v["before"], v["after"], round(v["after"] - v["before"], 1)])
    dims.append(["OVERALL", m["overall_before"], m["overall_after"],
                 round(m["overall_after"] - m["overall_before"], 1)])
    dims += [[], ["Run summary", ""]] + [[k, v] for k, v in rf.items()]
    put(sh, "Quality Scorecard", dims)

    # ---- BEFORE / AFTER on the same record ids ----
    master = pd.read_excel(os.path.join(OUT, "01_Cleaned_Master.xlsx"), dtype=str)
    raw = pd.read_csv(os.path.join(DATA, "messy_customers_25k.csv"), dtype=str, keep_default_na=False)
    ids = master["record_id"].astype(int).head(SAMPLE).tolist()
    before = raw[raw["record_id"].astype(int).isin(ids)]
    after = master.head(SAMPLE)
    put(sh, "BEFORE (messy input)", frame_to_values(before), vio="RAW")
    put(sh, "AFTER (clean master)",
        frame_to_values(after, numeric=("total_spent_usd", "order_count")), vio="RAW")

    # ---- Quarantine (all) ----
    quar = pd.read_excel(os.path.join(OUT, "02_Quarantine.xlsx"), dtype=str)
    put(sh, "Quarantine", frame_to_values(quar), vio="RAW")

    # ---- Change log sample ----
    log = pd.read_csv(os.path.join(OUT, "03_Change_Log.csv"), dtype=str,
                      keep_default_na=False, nrows=LOG_SAMPLE)
    put(sh, "Change log (sample)", frame_to_values(log), vio="RAW")

    finalize(sh)

    for ws in sh.worksheets():
        if ws.title in ("Sheet1", "Лист1"):
            sh.del_worksheet(ws)
            print("[OK] removed default tab")
    print("[OK] done:", sh.url)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("[ERR] pass the spreadsheet URL or id")
        sys.exit(1)
    main(sys.argv[1])
