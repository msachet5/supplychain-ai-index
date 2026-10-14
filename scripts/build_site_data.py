#!/usr/bin/env python3
"""Build site/data.js from the CSV tables in data/.

Real rows are used wherever they exist. Where employment, allocation or score
rows are still missing, deterministic placeholder values are filled in and
flagged, so the dashboard can be designed before the research is done.

Usage: python3 scripts/build_site_data.py
"""

import csv
import json
import random
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "site" / "data.js"

COUNTRIES = ("US", "CA")

# Placeholder priors per module: US workers (thousands), US mean wage (USD thousands).
# Rough orders of magnitude so the layout looks realistic. NOT research.
PLACEHOLDER_US = {
    "IBP": (200, 92), "PP": (450, 58), "SRC": (700, 76), "MFG": (7500, 50), "QM": (600, 50),
    "EAM": (900, 62), "EWM": (6000, 41), "TM": (420, 74), "FX": (3700, 56), "VIS": (150, 80),
    "O2C": (2000, 72), "GTS": (60, 70), "RET": (150, 42),
}
PLACEHOLDER_CA_WORKERS = 0.11   # Canada workers as a share of US
PLACEHOLDER_CA_WAGE_USD = 0.78  # Canadian mean wage in USD as a share of US

PLACEHOLDER_AI_TYPE = {
    "IBP": "ml|optimization", "PP": "optimization", "SRC": "genai|agentic", "MFG": "robotics|vision",
    "QM": "vision", "EAM": "ml", "EWM": "robotics|optimization", "TM": "optimization|agentic",
    "FX": "autonomy", "VIS": "ml", "O2C": "genai|agentic", "GTS": "genai", "RET": "vision|genai",
}
PLACEHOLDER_CAPABILITY = {"digital": (5.5, 9.2), "mixed": (3.5, 6.8), "physical": (1.0, 4.2)}

# Display names for vendor HQ countries ("Toronto, CA" would read as California).
COUNTRY_NAMES = {
    "US": "USA", "CA": "Canada", "GB": "UK", "FI": "Finland", "FR": "France", "DE": "Germany", "IE": "Ireland",
    "NL": "Netherlands", "NO": "Norway", "IL": "Israel", "AT": "Austria", "CZ": "Czechia", "SE": "Sweden",
}


def read(name):
    with (DATA / f"{name}.csv").open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def rng(key):
    return random.Random(f"scai:{key}")


def placeholder_metrics(processes):
    """Split each module's placeholder workforce across its processes with seeded weights."""
    by_module = defaultdict(list)
    for p in processes:
        by_module[p["module_id"]].append(p["process_id"])

    out = {}
    for module_id, pids in by_module.items():
        workers_k, wage_k = PLACEHOLDER_US[module_id]
        weights = {pid: rng(pid).uniform(0.4, 1.6) for pid in pids}
        total = sum(weights.values())
        for pid in pids:
            r = rng(pid + ":wage")
            us_workers = workers_k * 1000 * weights[pid] / total
            us_wage = wage_k * 1000 * r.uniform(0.85, 1.15)
            ca_workers = us_workers * PLACEHOLDER_CA_WORKERS
            ca_wage = us_wage * PLACEHOLDER_CA_WAGE_USD
            out[pid] = {
                "US": [us_workers, us_workers * us_wage],
                "CA": [ca_workers, ca_workers * ca_wage],
            }
    return out


def real_metrics(processes, occupations, stats, allocation, crosswalk, fx):
    """Process and occupation totals per country.

    in-scope workers = employment × crosswalk weight (CA) × scope share
    process workers  = Σ in-scope workers × time share
    process wages    = Σ in-scope workers × time share × mean wage (USD)
    Returns (by_process, by_soc, contributions) where contributions[pid][soc] = NA workers.
    """
    shares = defaultdict(list)
    for r in allocation:
        shares[r["soc_code"]].append((r["process_id"], float(r["time_share"])))
    scope = {o["soc_code"]: float(o["scope_share"]) for o in occupations}
    noc_to_soc = defaultdict(list)
    for r in crosswalk:
        soc_scope = float(r["scope_share"]) if r["scope_share"] else scope[r["soc_code"]]
        noc_to_soc[r["noc_code"]].append((r["soc_code"], float(r["weight"]), soc_scope))
    fx_rate = {(r["year"], r["currency"]): float(r["usd_per_unit"]) for r in fx}
    latest = {}
    for r in stats:
        latest[r["country"]] = max(latest.get(r["country"], ""), r["year"])

    by_process = {p["process_id"]: {c: [0.0, 0.0] for c in COUNTRIES} for p in processes}
    by_soc = defaultdict(lambda: {c: [0.0, 0.0] for c in COUNTRIES})
    contributions = defaultdict(lambda: defaultdict(float))
    for r in stats:
        country = r["country"]
        if country not in COUNTRIES or r["year"] != latest[country]:
            continue
        if r["currency"] == "USD":
            rate = 1.0
        elif (r["year"], r["currency"]) in fx_rate:
            rate = fx_rate[(r["year"], r["currency"])]
        else:
            raise SystemExit(f"fx_rates.csv has no {r['currency']} rate for {r['year']}")
        employment, wage = float(r["employment"]), float(r["mean_annual_wage"]) * rate
        if country == "US":
            socs = [(r["occ_code"], 1.0, scope.get(r["occ_code"], 0))]
        else:
            socs = noc_to_soc[r["occ_code"]]
        for soc, weight, soc_scope in socs:
            in_scope = employment * weight * soc_scope
            if not in_scope:
                continue
            by_soc[soc][country][0] += in_scope
            by_soc[soc][country][1] += in_scope * wage
            for pid, share in shares.get(soc, []):
                by_process[pid][country][0] += in_scope * share
                by_process[pid][country][1] += in_scope * share * wage
                contributions[pid][soc] += in_scope * share
    return by_process, by_soc, contributions


def per_country(pair_by_country):
    out = {c: {"workers": round(pair_by_country[c][0]), "wages": round(pair_by_country[c][1])} for c in COUNTRIES}
    out["NA"] = {k: sum(out[c][k] for c in COUNTRIES) for k in ("workers", "wages")}
    return out


def latest_scores(score_rows):
    best = {}
    for r in score_rows:
        if r["process_id"] not in best or int(r["version"]) > int(best[r["process_id"]]["version"]):
            best[r["process_id"]] = r
    return best


def placeholder_score(p):
    r = rng(p["process_id"] + ":score")
    lo, hi = PLACEHOLDER_CAPABILITY[p["work_type"]]
    capability = r.uniform(lo, hi)
    adoption = min(10.0, capability * r.uniform(0.3, 1.15))
    return {
        "capability": round(capability, 1),
        "adoption": round(adoption, 1),
        "ai_type": PLACEHOLDER_AI_TYPE[p["module_id"]].split("|"),
        "scored_by": "placeholder",
        "rationale": "",
    }


def main():
    modules = read("modules")
    processes = read("processes")
    occupations = read("occupations")
    stats, allocation = read("occupation_stats"), read("allocation")
    scores = latest_scores(read("process_scores"))

    solutions = {s["solution_id"]: s for s in read("solutions")}
    products = defaultdict(list)
    for link in read("process_solutions"):
        s = solutions[link["solution_id"]]
        products[link["process_id"]].append({
            "vendor": s["vendor"], "product": s["product"], "note": link["note"], "maturity": link["maturity"],
            "hq": ", ".join(x for x in (s["hq_city"], COUNTRY_NAMES.get(s["hq_country"], s["hq_country"])) if x),
            "url": s["url"],
        })

    evidence = defaultdict(list)
    for e in read("evidence"):
        evidence[e["process_id"]].append({
            "company": e["company"], "claim": e["claim"], "metric": e["metric"], "value": e["value"],
            "year": e["year"], "source_type": e["source_type"], "url": e["source_url"],
        })

    metrics_are_real = bool(stats and allocation)
    if metrics_are_real:
        metrics, by_soc, contributions = real_metrics(
            processes, occupations, stats, allocation, read("crosswalk_soc_noc"), read("fx_rates"))
    else:
        metrics, by_soc, contributions = placeholder_metrics(processes), {}, {}

    titles = {o["soc_code"]: o["title"] for o in occupations}
    out_processes = []
    for p in processes:
        pid = p["process_id"]
        top_jobs = sorted(contributions.get(pid, {}).items(), key=lambda kv: -kv[1])[:6]

        s = scores.get(pid)
        if s:
            score = {
                "capability": float(s["capability"]),
                "adoption": float(s["adoption"]),
                "ai_type": [t for t in s["ai_type"].split("|") if t],
                "scored_by": s["scored_by"],
                "rationale": s["rationale"],
            }
        else:
            score = placeholder_score(p)

        out_processes.append({
            "id": pid,
            "module": p["module_id"],
            "name": p["name"],
            "description": p["description"],
            "work_type": p["work_type"],
            "hand_score": p["hand_score"] == "yes",
            "metrics": per_country(metrics[pid]),
            "jobs": [{"soc": soc, "title": titles[soc], "workers": round(w)} for soc, w in top_jobs],
            "products": products.get(pid, []),
            "evidence": sorted(evidence.get(pid, []), key=lambda e: e["year"], reverse=True),
            **score,
        })

    # Role search: every in-scope occupation, with its time split, tasks and job-title aliases.
    alloc_by_soc = defaultdict(list)
    for r in allocation:
        alloc_by_soc[r["soc_code"]].append([r["process_id"], float(r["time_share"])])
    tasks = defaultdict(list)
    for r in read("role_tasks"):
        tasks[r["soc_code"]].append(r["task"])
    aliases, alias_notes = defaultdict(list), {}
    for r in read("role_aliases"):
        aliases[r["soc_code"]].append(r["alias"])
        if r["note"]:
            alias_notes[r["alias"]] = r["note"]
    roles = []
    for o in occupations:
        if o["in_scope"] == "no":
            continue
        soc = o["soc_code"]
        roles.append({
            "soc": soc, "title": o["title"], "aliases": aliases.get(soc, []),
            "scope": o["in_scope"], "scope_share": float(o["scope_share"]), "scope_note": o["scope_note"],
            "metrics": per_country(by_soc[soc]) if soc in by_soc else None,
            "alloc": sorted(alloc_by_soc.get(soc, []), key=lambda a: -a[1]),
            "tasks": tasks.get(soc, []),
        })

    payload = {
        "generated": date.today().isoformat(),
        "placeholder": {
            "metrics": not metrics_are_real,
            "scores": sum(1 for p in out_processes if p["scored_by"] == "placeholder"),
            "llm_scores": sum(1 for p in out_processes if p["scored_by"] == "llm"),
        },
        "modules": [{
            "id": m["module_id"], "name": m["name"], "short": m["short_label"], "sap": m["sap_reference"],
            "has_sap": m["has_sap_module"] == "yes", "stage": m["stage"], "description": m["description"],
        } for m in sorted(modules, key=lambda m: int(m["sort_order"]))],
        "processes": out_processes,
        "roles": roles,
        "alias_notes": alias_notes,
        "sources": {
            "US": "BLS OEWS May 2025",
            "CA": "ESDC COPS (2023 employment) and Job Bank 2025 wages, via a hand-checked NOC–SOC crosswalk",
            "fx": next((r["source"] for r in read("fx_rates")), ""),
            "tasks": "O*NET 31.0",
        },
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("// Generated by scripts/build_site_data.py. Do not edit by hand.\n"
                   f"window.SCAI_DATA = {json.dumps(payload, separators=(',', ':'))};\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KB): {len(out_processes)} processes, "
          f"{len(roles)} roles, metrics {'real' if metrics_are_real else 'PLACEHOLDER'}, "
          f"{payload['placeholder']['llm_scores']} LLM first-pass scores, {payload['placeholder']['scores']} placeholder scores")


if __name__ == "__main__":
    main()
