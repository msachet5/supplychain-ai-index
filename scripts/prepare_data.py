#!/usr/bin/env python3
"""Turn the raw public files in data/raw/ into the project tables.

Writes:
  data/occupation_stats.csv   US (BLS OEWS May 2025) and Canada (ESDC COPS + Job Bank) employment and mean wages
  data/crosswalk_soc_noc.csv  Canadian NOC 2021 -> US SOC, with employment weights (hand-checked via crosswalk_overrides.csv)
  data/fx_rates.csv           Bank of Canada annual average CAD/USD
  data/role_tasks.csv         Top O*NET 31.0 tasks per in-scope occupation, for the role view

Usage: python3 -I scripts/prepare_data.py   (run scripts/fetch_data.sh first)
"""

import csv
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"

YEAR = "2025"
HOURS_PER_YEAR = 2080  # same full-time convention BLS uses to annualize hourly wages
TASKS_PER_ROLE = 6

# OEWS publishes some occupations only as aggregates; map detailed SOC codes onto them.
OEWS_AGGREGATE = {
    "13-1021": "13-1020", "13-1022": "13-1020", "13-1023": "13-1020",
    "51-2092": "51-2090", "51-2099": "51-2090",
    "53-1042": "53-1047", "53-1043": "53-1047", "53-1044": "53-1047", "53-1049": "53-1047",
}

# Which O*NET occupations describe the in-scope part of each SOC (default: the SOC's .00 code).
ONET_SELECT = {
    "11-3051": ["11-3051.00", "11-3051.01"],
    "11-3071": ["11-3071.00", "11-3071.04"],
    "13-1020": ["13-1021.00", "13-1022.00", "13-1023.00"],
    "13-1041": ["13-1041.08"],
    "13-1081": ["13-1081.00", "13-1081.01", "13-1081.02"],
    "17-2112": ["17-2112.00", "17-2112.03"],
    "43-5011": ["43-5011.00", "43-5011.01"],
    "51-2090": ["51-2092.00", "51-2099.00"],
    "53-1047": ["53-1042.00", "53-1043.00"],
    "53-6051": ["53-6051.07"],
}

SOURCES = {
    "US": ("BLS OEWS May 2025 national", "https://data.bls.gov/oes/#/area/0000000/2025"),
    "CA": ("ESDC COPS 2023 employment; Job Bank 2025 wages",
           "https://open.canada.ca/data/dataset/adad580f-76b0-4502-bd05-20c125de9116"),
}


def read_csv(path, encoding="utf-8"):
    with path.open(newline="", encoding=encoding) as f:
        return list(csv.DictReader(f))


def write_csv(path, fields, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {path.relative_to(ROOT)}: {len(rows)} rows")


def number(text):
    text = (text or "").replace(",", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


def main():
    occupations = read_csv(DATA / "occupations.csv")
    listed = {o["soc_code"] for o in occupations}
    in_scope = {o["soc_code"] for o in occupations if o["in_scope"] != "no"}

    # --- US ---
    stats = []
    for r in read_csv(RAW / "bls" / "oews_national_may2025.csv"):
        emp, wage = number(r["employment"]), number(r["mean_annual_wage"])
        if r["soc_code"] in listed and emp is not None and wage is not None:
            stats.append({"country": "US", "code_system": "SOC2018", "occ_code": r["soc_code"], "year": YEAR,
                          "employment": int(emp), "mean_annual_wage": int(wage), "currency": "USD",
                          "source": SOURCES["US"][0], "source_url": SOURCES["US"][1]})
    us_emp_all = {r["soc_code"]: number(r["employment"]) or 0
                  for r in read_csv(RAW / "bls" / "oews_national_may2025_employment_all.csv")}

    # --- Canada: NOC -> SOC crosswalk, weighted by US employment within each NOC ---
    noc_title, noc_socs = {}, defaultdict(set)
    for r in read_csv(RAW / "dais" / "noc2021_onet26.csv"):
        noc = r["noc"].strip().zfill(5)
        soc = r["onet"][:7]
        noc_title[noc] = r["noc_title"]
        noc_socs[noc].add(OEWS_AGGREGATE.get(soc, soc))

    cops_rows = read_csv(RAW / "cops" / "employment_2024_2033_noc2021.csv", "latin-1")
    cops = {r["Code"]: number(r["2023"]) for r in cops_rows}
    noc_title.update({r["Code"]: r["Occupation Name"] for r in cops_rows if r["Code"] not in noc_title})

    crosswalk = []
    for noc, socs in sorted(noc_socs.items()):
        if not socs & in_scope:
            continue
        total = sum(us_emp_all.get(s, 0) for s in socs)
        for soc in sorted(socs & listed):
            weight = us_emp_all.get(soc, 0) / total if total else 1 / len(socs)
            if weight > 0:
                crosswalk.append({"soc_code": soc, "noc_code": noc, "noc_title": noc_title[noc], "weight": f"{weight:.4f}",
                                  "scope_share": "", "source": "The Dais NOC 2021-O*NET 26 crosswalk; US employment weights"})

    # Hand-checked overrides replace every Dais row for a NOC; soc_code "-" drops the NOC.
    overrides = defaultdict(list)
    for r in read_csv(DATA / "crosswalk_overrides.csv"):
        overrides[r["noc_code"]].append(r)
    crosswalk = [c for c in crosswalk if c["noc_code"] not in overrides]
    for noc, rows in overrides.items():
        for r in rows:
            if r["soc_code"] != "-":
                crosswalk.append({"soc_code": r["soc_code"], "noc_code": noc, "noc_title": noc_title.get(noc, ""),
                                  "weight": r["weight"], "scope_share": r["scope_share"], "source": f"Hand-checked: {r['note']}"})
    crosswalk.sort(key=lambda c: (c["noc_code"], c["soc_code"]))
    nocs_needed = {c["noc_code"] for c in crosswalk}
    wages = {}
    for r in read_csv(RAW / "jobbank" / "wages_2025.csv", "utf-8-sig"):
        if r["prov"] != "NAT":
            continue
        noc = r["NOC_CNP"].replace("NOC_", "")
        wage = number(r["Average_Wage_Salaire_Moyen"]) or number(r["Median_Wage_Salaire_Median"])
        if wage is not None:
            wages[noc] = wage if r["Annual_Wage_Flag_Salaire_annuel"] == "1" else wage * HOURS_PER_YEAR

    skipped = []
    for noc in sorted(nocs_needed):
        emp, wage = cops.get(noc), wages.get(noc)
        if not emp or not wage:
            skipped.append(noc)
            continue
        stats.append({"country": "CA", "code_system": "NOC2021", "occ_code": noc, "year": YEAR,
                      "employment": int(emp), "mean_annual_wage": int(round(wage)), "currency": "CAD",
                      "source": SOURCES["CA"][0], "source_url": SOURCES["CA"][1]})
    if skipped:
        print(f"Canada: no employment or wage for NOC {', '.join(skipped)}; left out")
        crosswalk = [c for c in crosswalk if c["noc_code"] not in skipped]

    write_csv(DATA / "occupation_stats.csv",
              ["country", "code_system", "occ_code", "year", "employment", "mean_annual_wage", "currency", "source", "source_url"], stats)
    write_csv(DATA / "crosswalk_soc_noc.csv", ["soc_code", "noc_code", "noc_title", "weight", "scope_share", "source"], crosswalk)

    # --- FX ---
    obs = json.loads((RAW / "boc" / "fx_annual_usdcad.json").read_text())["observations"]
    cad_per_usd = {o["d"][:4]: float(o["FXAUSDCAD"]["v"]) for o in obs}
    write_csv(DATA / "fx_rates.csv", ["year", "currency", "usd_per_unit", "source"],
              [{"year": YEAR, "currency": "CAD", "usd_per_unit": f"{1 / cad_per_usd[YEAR]:.5f}",
                "source": f"Bank of Canada annual average FXAUSDCAD {YEAR} ({cad_per_usd[YEAR]} CAD per USD)"}])

    # --- O*NET tasks for the role view ---
    importance = {}
    for r in read_csv(RAW / "onet" / "task_ratings.csv"):
        if r["Scale ID"] == "IM":
            importance[(r["O*NET-SOC Code"], r["Task ID"])] = float(r["Data Value"])
    by_code = defaultdict(list)
    for r in read_csv(RAW / "onet" / "task_statements.csv"):
        by_code[r["O*NET-SOC Code"]].append(r)

    role_tasks = []
    for soc in sorted(in_scope):
        codes = ONET_SELECT.get(soc, [f"{soc}.00"])
        ranked = sorted(
            ((importance.get((c, t["Task ID"]), 0), t["Task"], c) for c in codes for t in by_code.get(c, [])),
            key=lambda x: -x[0])
        seen = set()
        for imp, text, code in ranked:
            if text in seen:
                continue
            seen.add(text)
            role_tasks.append({"soc_code": soc, "rank": len(seen), "task": text, "importance": f"{imp:.2f}", "onet_code": code})
            if len(seen) == TASKS_PER_ROLE:
                break
    write_csv(DATA / "role_tasks.csv", ["soc_code", "rank", "task", "importance", "onet_code"], role_tasks)


if __name__ == "__main__":
    main()
