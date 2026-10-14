#!/usr/bin/env python3
"""Check the CSV tables in data/ for schema, key and range problems.

Errors (exit code 1) are things that would break the build.
Warnings are coverage gaps that are expected while the data is being filled in.

Usage: python3 scripts/validate.py
"""

import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"

SCHEMA = {
    "modules": ["module_id", "name", "short_label", "sap_reference", "has_sap_module", "stage", "scor_domain", "sort_order", "description"],
    "processes": ["process_id", "module_id", "name", "work_type", "hand_score", "sort_order", "description"],
    "occupations": ["soc_code", "title", "soc_major_group", "in_scope", "scope_share", "primary_module", "scope_note"],
    "crosswalk_soc_noc": ["soc_code", "noc_code", "noc_title", "weight", "scope_share", "source"],
    "crosswalk_overrides": ["noc_code", "soc_code", "weight", "scope_share", "note"],
    "role_aliases": ["alias", "soc_code", "note"],
    "role_splits": ["alias", "process_id", "time_share", "method", "confidence", "note"],
    "role_tasks": ["soc_code", "rank", "task", "importance", "onet_code"],
    "occupation_stats": ["country", "code_system", "occ_code", "year", "employment", "mean_annual_wage", "currency", "source", "source_url"],
    "allocation": ["soc_code", "process_id", "time_share", "method", "confidence", "note"],
    "process_scores": ["process_id", "version", "capability", "adoption", "ai_type", "digital_share", "data_readiness",
                       "decision_stakes", "scored_by", "scored_on", "rationale", "override_note"],
    "solutions": ["solution_id", "vendor", "product", "hq_city", "hq_country", "ai_type", "url"],
    "process_solutions": ["process_id", "solution_id", "maturity", "note"],
    "evidence": ["evidence_id", "process_id", "company", "solution_id", "claim", "metric", "value", "year", "source_type", "source_url"],
    "fx_rates": ["year", "currency", "usd_per_unit", "source"],
}

YES_NO = {"yes", "no"}
LEVELS = {"low", "med", "high"}
WORK_TYPES = {"digital", "physical", "mixed"}
SCOPES = {"full", "partial", "no"}
AI_TYPES = {"ml", "genai", "agentic", "optimization", "vision", "robotics", "autonomy"}
SCORED_BY = {"llm", "expert", "llm+expert"}
METHODS = {"onet_tasks", "expert", "llm"}
MATURITY = {"ga", "pilot", "announced"}
SOURCE_TYPES = {"independent", "vendor_claimed", "analyst", "news"}
COUNTRY_SYSTEM = {"US": "SOC2018", "CA": "NOC2021", "MX": "SINCO2019"}
COUNTRY_CURRENCY = {"US": "USD", "CA": "CAD", "MX": "MXN"}
SOC_RE = re.compile(r"^\d{2}-\d{4}$")
TOLERANCE = 0.001

errors, warnings = [], []


def err(table, row_no, msg):
    errors.append(f"{table}.csv line {row_no}: {msg}")


def warn(msg):
    warnings.append(msg)


def load(table):
    path = DATA / f"{table}.csv"
    if not path.exists():
        errors.append(f"{table}.csv: file missing")
        return []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != SCHEMA[table]:
            errors.append(f"{table}.csv: header is {reader.fieldnames}, expected {SCHEMA[table]}")
            return []
        # line 1 is the header, so data rows start at line 2
        return [(i, row) for i, row in enumerate(reader, start=2)]


def number(table, row_no, row, col, lo=None, hi=None, required=True):
    raw = row[col].strip()
    if not raw:
        if required:
            err(table, row_no, f"{col} is empty")
        return None
    try:
        val = float(raw)
    except ValueError:
        err(table, row_no, f"{col}={raw!r} is not a number")
        return None
    if (lo is not None and val < lo) or (hi is not None and val > hi):
        err(table, row_no, f"{col}={raw} outside [{lo}, {hi}]")
    return val


def enum(table, row_no, row, col, allowed, required=True):
    val = row[col].strip()
    if not val and not required:
        return val
    if val not in allowed:
        err(table, row_no, f"{col}={val!r} not in {sorted(allowed)}")
    return val


def unique(table, rows, key):
    seen = set()
    for row_no, row in rows:
        k = tuple(row[c] for c in key) if isinstance(key, tuple) else row[key]
        if k in seen:
            err(table, row_no, f"duplicate key {k}")
        seen.add(k)
    return seen


def main():
    t = {name: load(name) for name in SCHEMA}

    # --- taxonomy ---
    module_ids = unique("modules", t["modules"], "module_id")
    for n, r in t["modules"]:
        enum("modules", n, r, "has_sap_module", YES_NO)
        number("modules", n, r, "sort_order", lo=1)

    process_ids = unique("processes", t["processes"], "process_id")
    hand_scored = set()
    for n, r in t["processes"]:
        if r["module_id"] not in module_ids:
            err("processes", n, f"unknown module_id {r['module_id']!r}")
        elif not r["process_id"].startswith(r["module_id"] + "-"):
            err("processes", n, f"process_id {r['process_id']} does not start with {r['module_id']}-")
        enum("processes", n, r, "work_type", WORK_TYPES)
        if enum("processes", n, r, "hand_score", YES_NO) == "yes":
            hand_scored.add(r["process_id"])

    # --- occupations and crosswalk ---
    soc_codes = unique("occupations", t["occupations"], "soc_code")
    in_scope = set()
    for n, r in t["occupations"]:
        if not SOC_RE.match(r["soc_code"]):
            err("occupations", n, f"soc_code {r['soc_code']!r} is not NN-NNNN")
        scope = enum("occupations", n, r, "in_scope", SCOPES)
        if scope in ("full", "partial"):
            in_scope.add(r["soc_code"])
            if r["primary_module"] not in module_ids:
                err("occupations", n, f"in-scope occupation needs a valid primary_module, got {r['primary_module']!r}")
        elif scope == "no" and r["primary_module"]:
            err("occupations", n, "out-of-scope occupation should have an empty primary_module")
        share = number("occupations", n, r, "scope_share", lo=0, hi=1)
        if share is not None:
            if scope == "full" and share != 1:
                err("occupations", n, "full-scope occupation needs scope_share 1")
            if scope == "no" and share != 0:
                err("occupations", n, "out-of-scope occupation needs scope_share 0")
            if scope == "partial" and not 0 < share < 1:
                err("occupations", n, "partial occupation needs 0 < scope_share < 1")

    unique("crosswalk_soc_noc", t["crosswalk_soc_noc"], ("soc_code", "noc_code"))
    noc_weight = defaultdict(float)
    for n, r in t["crosswalk_soc_noc"]:
        if r["soc_code"] not in soc_codes:
            err("crosswalk_soc_noc", n, f"unknown soc_code {r['soc_code']!r}")
        w = number("crosswalk_soc_noc", n, r, "weight", lo=0, hi=1)
        if w is not None:
            noc_weight[r["noc_code"]] += w
        number("crosswalk_soc_noc", n, r, "scope_share", lo=0, hi=1, required=False)
    # Weights can sum to less than 1: the rest of the NOC maps to occupations outside the list.
    for noc, total in noc_weight.items():
        if total > 1 + TOLERANCE:
            errors.append(f"crosswalk_soc_noc.csv: weights for NOC {noc} sum to {total:.3f}, must be <= 1")
    override_weight = defaultdict(float)
    for n, r in t["crosswalk_overrides"]:
        if r["soc_code"] == "-":
            continue
        if r["soc_code"] not in soc_codes:
            err("crosswalk_overrides", n, f"unknown soc_code {r['soc_code']!r}")
        w = number("crosswalk_overrides", n, r, "weight", lo=0, hi=1)
        if w is not None:
            override_weight[r["noc_code"]] += w
        number("crosswalk_overrides", n, r, "scope_share", lo=0, hi=1, required=False)
    for noc, total in override_weight.items():
        if total > 1 + TOLERANCE:
            errors.append(f"crosswalk_overrides.csv: weights for NOC {noc} sum to {total:.3f}, must be <= 1")

    # --- role search ---
    unique("role_aliases", t["role_aliases"], "alias")
    for n, r in t["role_aliases"]:
        if r["soc_code"] not in in_scope:
            err("role_aliases", n, f"soc_code {r['soc_code']!r} is not an in-scope occupation")
    aliases = {r["alias"] for _, r in t["role_aliases"]}
    unique("role_splits", t["role_splits"], ("alias", "process_id"))
    share_by_alias = defaultdict(float)
    for n, r in t["role_splits"]:
        if r["alias"] not in aliases:
            err("role_splits", n, f"alias {r['alias']!r} is not in role_aliases.csv")
        if r["process_id"] not in process_ids:
            err("role_splits", n, f"unknown process_id {r['process_id']!r}")
        s = number("role_splits", n, r, "time_share", lo=0, hi=1)
        if s is not None:
            share_by_alias[r["alias"]] += s
        enum("role_splits", n, r, "method", METHODS)
        enum("role_splits", n, r, "confidence", LEVELS)
    for alias, total in share_by_alias.items():
        if total > 1 + TOLERANCE:
            errors.append(f"role_splits.csv: time_share for {alias!r} sums to {total:.3f}, must be <= 1")
    unique("role_tasks", t["role_tasks"], ("soc_code", "rank"))
    for n, r in t["role_tasks"]:
        if r["soc_code"] not in in_scope:
            err("role_tasks", n, f"soc_code {r['soc_code']!r} is not an in-scope occupation")
    noc_codes = set(noc_weight)

    # --- stats ---
    unique("occupation_stats", t["occupation_stats"], ("country", "occ_code", "year"))
    for n, r in t["occupation_stats"]:
        country = enum("occupation_stats", n, r, "country", set(COUNTRY_SYSTEM))
        if country in COUNTRY_SYSTEM:
            if r["code_system"] != COUNTRY_SYSTEM[country]:
                err("occupation_stats", n, f"{country} rows must use code_system {COUNTRY_SYSTEM[country]}")
            if r["currency"] != COUNTRY_CURRENCY[country]:
                err("occupation_stats", n, f"{country} rows must use currency {COUNTRY_CURRENCY[country]}")
            if country == "US" and r["occ_code"] not in soc_codes:
                err("occupation_stats", n, f"US occ_code {r['occ_code']!r} not in occupations.csv")
            if country == "CA" and r["occ_code"] not in noc_codes:
                err("occupation_stats", n, f"CA occ_code {r['occ_code']!r} not in crosswalk_soc_noc.csv")
        number("occupation_stats", n, r, "year", lo=2000, hi=2100)
        number("occupation_stats", n, r, "employment", lo=0)
        number("occupation_stats", n, r, "mean_annual_wage", lo=0)
        if not r["source_url"].strip():
            err("occupation_stats", n, "source_url is empty")

    # --- allocation ---
    unique("allocation", t["allocation"], ("soc_code", "process_id"))
    share_by_soc = defaultdict(float)
    allocated_processes = set()
    for n, r in t["allocation"]:
        if r["soc_code"] not in in_scope:
            err("allocation", n, f"soc_code {r['soc_code']!r} is not an in-scope occupation")
        if r["process_id"] not in process_ids:
            err("allocation", n, f"unknown process_id {r['process_id']!r}")
        s = number("allocation", n, r, "time_share", lo=0, hi=1)
        if s is not None:
            share_by_soc[r["soc_code"]] += s
            allocated_processes.add(r["process_id"])
        enum("allocation", n, r, "method", METHODS)
        enum("allocation", n, r, "confidence", LEVELS)
    for soc, total in share_by_soc.items():
        if total > 1 + TOLERANCE:
            errors.append(f"allocation.csv: time_share for {soc} sums to {total:.3f}, must be <= 1")

    # --- scores ---
    unique("process_scores", t["process_scores"], ("process_id", "version"))
    expert_scored, scored = set(), set()
    for n, r in t["process_scores"]:
        if r["process_id"] not in process_ids:
            err("process_scores", n, f"unknown process_id {r['process_id']!r}")
        number("process_scores", n, r, "capability", lo=0, hi=10)
        number("process_scores", n, r, "adoption", lo=0, hi=10)
        number("process_scores", n, r, "digital_share", lo=0, hi=1)
        for part in filter(None, r["ai_type"].split("|")):
            if part not in AI_TYPES:
                err("process_scores", n, f"ai_type part {part!r} not in {sorted(AI_TYPES)}")
        enum("process_scores", n, r, "data_readiness", LEVELS)
        enum("process_scores", n, r, "decision_stakes", LEVELS)
        by = enum("process_scores", n, r, "scored_by", SCORED_BY)
        if not r["rationale"].strip():
            err("process_scores", n, "rationale is empty")
        scored.add(r["process_id"])
        if by in ("expert", "llm+expert"):
            expert_scored.add(r["process_id"])

    # --- click panel ---
    solution_ids = unique("solutions", t["solutions"], "solution_id")
    for n, r in t["solutions"]:
        if r["url"] and not r["url"].startswith("https://"):
            err("solutions", n, f"url {r['url']!r} must start with https://")
        for part in filter(None, r["ai_type"].split("|")):
            if part not in AI_TYPES:
                err("solutions", n, f"ai_type part {part!r} not in {sorted(AI_TYPES)}")

    unique("process_solutions", t["process_solutions"], ("process_id", "solution_id"))
    for n, r in t["process_solutions"]:
        if r["process_id"] not in process_ids:
            err("process_solutions", n, f"unknown process_id {r['process_id']!r}")
        if r["solution_id"] not in solution_ids:
            err("process_solutions", n, f"unknown solution_id {r['solution_id']!r}")
        enum("process_solutions", n, r, "maturity", MATURITY)

    unique("evidence", t["evidence"], "evidence_id")
    for n, r in t["evidence"]:
        if r["process_id"] not in process_ids:
            err("evidence", n, f"unknown process_id {r['process_id']!r}")
        if r["solution_id"] and r["solution_id"] not in solution_ids:
            err("evidence", n, f"unknown solution_id {r['solution_id']!r}")
        enum("evidence", n, r, "source_type", SOURCE_TYPES)
        number("evidence", n, r, "year", lo=2000, hi=2100)
        if not r["source_url"].strip():
            err("evidence", n, "source_url is empty")

    unique("fx_rates", t["fx_rates"], ("year", "currency"))
    for n, r in t["fx_rates"]:
        enum("fx_rates", n, r, "currency", {"CAD", "MXN"})
        number("fx_rates", n, r, "usd_per_unit", lo=0)

    # --- coverage (warnings) ---
    def gap(label, missing):
        if missing:
            sample = ", ".join(sorted(missing)[:5])
            more = f" (+{len(missing) - 5} more)" if len(missing) > 5 else ""
            warn(f"{len(missing)} {label}: {sample}{more}")

    gap("in-scope occupations have no allocation rows", in_scope - set(share_by_soc))
    gap("processes have no workers allocated", process_ids - allocated_processes)
    gap("processes have no score", process_ids - scored)
    gap("hand_score processes have no expert score", hand_scored - expert_scored)
    full_scope = {r["soc_code"] for _, r in t["occupations"] if r["in_scope"] == "full"}
    gap("full-scope occupations allocate < 90% of time",
        {s for s in full_scope & set(share_by_soc) if share_by_soc[s] < 0.9})

    # --- report ---
    print(f"modules {len(module_ids)} | processes {len(process_ids)} ({len(hand_scored)} hand-scored) | "
          f"occupations {len(soc_codes)} ({len(in_scope)} in scope)")
    print(f"allocation rows {len(t['allocation'])} | scores {len(t['process_scores'])} | "
          f"solutions {len(solution_ids)} | evidence {len(t['evidence'])}")
    for w in warnings:
        print(f"WARN  {w}")
    for e in errors:
        print(f"ERROR {e}")
    print(f"\n{len(errors)} errors, {len(warnings)} warnings")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
