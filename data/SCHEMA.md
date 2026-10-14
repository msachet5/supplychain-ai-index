# Data dictionary

All tables are UTF-8 CSV with a header row. Run `python3 scripts/validate.py` after any edit.

## Pipeline

```
scripts/fetch_data.sh          public files → data/raw/            (BLS pulled by hand, see the script header)
scripts/prepare_data.py        data/raw/ → occupation_stats, crosswalk_soc_noc, fx_rates, role_tasks
scripts/validate.py            schema, key and range checks
scripts/build_site_data.py     data/*.csv → site/data.js
```

Hand-maintained tables (edit these directly): `modules`, `processes`, `occupations`, `allocation`, `process_scores`, `solutions`, `process_solutions`, `evidence`, `role_aliases`, `crosswalk_overrides`.
Generated tables (do not edit; re-run `prepare_data.py`): `occupation_stats`, `crosswalk_soc_noc`, `fx_rates`, `role_tasks`.

```
BLS OEWS · ESDC COPS · Job Bank · O*NET · Dais crosswalk · Bank of Canada
        ↓
occupations ─ crosswalk_soc_noc ─ occupation_stats ──→ allocation ──→ box_metrics ←── process_scores
                                                                          ↑
                                         modules ─ processes ─────────────┘
                                                      └── process_solutions ─ solutions,  evidence  (click panel)
```

## Scope

End to end, from buying materials through making, storing, moving and distributing to the customer's door, plus returns. Line workers and distributors are included. Farming and mining, the retail selling floor (cashiers, sales associates), R&D and utilities are excluded. Retail shelf stockers are included.

Geography: US and Canada. Mexico is phase 2 and will need INEGI ENOE microdata.

## Sources

| What | Source | Notes |
|---|---|---|
| US employment and mean annual wage | BLS OEWS, May 2025, national | Read from the BLS data tool; BLS blocks scripted downloads |
| Canadian employment | ESDC COPS 2024–2033 projections, 2023 column | 2023 is the last actual year in the file |
| Canadian wages | Job Bank 2025 open data, national rows | Average wage, else median; hourly × 2,080 |
| NOC ↔ SOC | The Dais `noc2021_onet26.csv` (MIT) | Split by US employment, then hand-checked in `crosswalk_overrides.csv` |
| CAD → USD | Bank of Canada FXAUSDCAD, 2025 annual average | 1.3978 CAD per USD |
| Job tasks | O*NET 31.0 task statements and importance ratings | Role view only |

Known gaps: 12 small NOC unit groups (for example 94101 foundry workers and 94102 glass forming) have no separate COPS figure and are left out of Canada's totals. US and Canadian years differ (2025 vs 2023 employment).

## Taxonomy (the boxes)

### modules.csv: level-1 boxes, modelled on SAP modules

| column | meaning |
|---|---|
| module_id | Short key, e.g. `TM` |
| name | Full module name, shown in the detail panel |
| short_label | 2–4 word plain-language description, shown in the treemap headers |
| sap_reference | SAP module this box is modelled on. Text reference only, no SAP branding on the site |
| has_sap_module | `yes` / `no` (Freight Execution has no SAP module) |
| stage | Plan, Source, Make, Maintain, Store, Move, Sell, Trade, Return |
| scor_domain | SCOR DS domain, for an alternate grouping |
| sort_order | Order within the treemap |
| description | One line for the tooltip |

### processes.csv: level-2 boxes

| column | meaning |
|---|---|
| process_id | `<module_id>-NN` |
| module_id | Parent module |
| name, description | Display text |
| work_type | `digital` / `physical` / `mixed` |
| hand_score | `yes` = to be scored by hand from domain experience (supply planning, transportation) |
| sort_order | Order within the module |

## Box size (people and money)

### occupations.csv: US SOC 2018 codes, as published in BLS OEWS

| column | meaning |
|---|---|
| soc_code | OEWS code. Some are OEWS aggregates, e.g. `13-1020`, `51-2090`, `53-1047` |
| title | Exact BLS title |
| in_scope | `full`, `partial`, or `no` (listed only to document the exclusion) |
| scope_share | Share of the occupation's workers doing supply chain work: 1 for `full`, 0 for `no`, an estimate for `partial` |
| primary_module | Main module, used for labels. The real split lives in `allocation` |
| scope_note | Why it is partial or excluded, and the basis for the estimate |

`scope_share` values for partial occupations are judgment estimates (for example, ~15% of customer service reps handle orders). Review them.

### crosswalk_soc_noc.csv (generated): Canadian NOC 2021 → US SOC

| column | meaning |
|---|---|
| soc_code, noc_code, noc_title | Key and label |
| weight | Share of the NOC's workers assigned to this SOC. Per NOC the weights sum to ≤ 1; the rest maps to occupations outside the list |
| scope_share | Optional Canada-specific scope share; blank = use the SOC's `scope_share` |
| source | Dais + US employment weights, or `Hand-checked: …` |

### crosswalk_overrides.csv: hand-checked NOC mappings

Any NOC listed here replaces all of its Dais rows. `soc_code` `-` drops the NOC (not supply chain). Use `scope_share` where the Canadian code is narrower than the US one (NOC 13200 customs brokers → 13-1041 at 100%).

### occupation_stats.csv (generated)

| column | meaning |
|---|---|
| country | `US` / `CA` |
| code_system | `SOC2018` for US, `NOC2021` for CA |
| occ_code | SOC or NOC code |
| year | Reference year (2025) |
| employment | Number of workers |
| mean_annual_wage | Mean, in local currency |
| currency | `USD` / `CAD` |
| source, source_url | Provenance |

### allocation.csv: how each occupation's time splits across processes

| column | meaning |
|---|---|
| soc_code, process_id | Key |
| time_share | 0–1. Per occupation the sum is ≤ 1 |
| method | `onet_tasks`, `expert`, or `llm` |
| confidence | `low` / `med` / `high` |
| note | e.g. `FAB template` for production families |

The current rows are an LLM first pass (`method=llm`). Production occupations use family templates (fabrication, assembly, process, packaging). Planning, logistics, procurement and sales occupations were split by reading their top O*NET tasks.

## Box colour and scatter position

### process_scores.csv

| column | meaning |
|---|---|
| process_id, version | Key. Bump `version` when re-scoring so changes can be shown over time |
| capability | 0–10: share of this process's work that current AI could do at acceptable quality with typical data. 0 none, 5 about half, 10 essentially all |
| adoption | 0–10: how widely AI is in production use for it across North American companies. 0 none, 2 early pilots, 4 leaders use it, 6 common among large firms, 8 mainstream, 10 universal |
| ai_type | One or more of `ml`, `genai`, `agentic`, `optimization`, `vision`, `robotics`, `autonomy`, separated by `\|` |
| digital_share | 0–1: share of the work that happens on a screen |
| data_readiness | `low` / `med` / `high` |
| decision_stakes | `low` / `med` / `high`: cost of a wrong call |
| scored_by | `llm`, `expert`, or `llm+expert` |
| scored_on | ISO date |
| rationale | Why this score. Required |
| override_note | If the expert changed the LLM's score, what changed and why |

Version 1 is an LLM first pass for all 94 processes. To hand-score, run local scoring mode (`python3 -I scripts/score_server.py`), which appends a new version with `scored_by=llm+expert`. You can also add the row by hand.

## Role search

- **role_aliases.csv**: everyday job titles → SOC (`alias`, `soc_code`, `note`). For example "Demand planner" → 13-1081 Logisticians, because there is no demand planner code.
- **role_tasks.csv** (generated): top 6 O*NET tasks per in-scope SOC by importance (`soc_code`, `rank`, `task`, `importance`, `onet_code`).

## Click panel

- **solutions.csv**: vendors and products (`solution_id`, vendor, product, HQ, `ai_type`, url).
- **process_solutions.csv**: links processes to solutions. `maturity` is `ga`, `pilot` or `announced`; `note` says what it does in that process.
- **evidence.csv**: real-world proof points (16 so far). `source_type` is `independent` (case study), `news`, `vendor_claimed` (a company's own figure), or `analyst`. `source_url` is required. Only add claims you have read in the source; where a popular figure could not be traced to a primary source (for example, McKinsey's "20–50% lower forecast error"), leave it out.

## Reference

- **fx_rates.csv** (generated): annual average USD per CAD.

## Calculated in build_site_data.py

```
in-scope workers = employment × crosswalk weight (CA only) × scope_share
process workers  = Σ in-scope workers × time_share
process wages    = Σ in-scope workers × time_share × mean wage (USD)   → treemap area
avg wage         = process wages / process workers                     → scatter bubble size
gap              = capability − adoption                               → colour toggle
role exposure    = Σ time_share × capability / Σ time_share × 10       → role card (0–100)
exposure index   = Σ wages × capability / Σ wages × 10                 → headline and group bars (0–100)
adoption index   = Σ wages × adoption / Σ wages × 10
```
