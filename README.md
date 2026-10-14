# Supply Chain AI Exposure Index

How much of North America's end-to-end supply chain work can AI do, and how much of it is actually deployed?

- **Process map:** a treemap of 13 SAP-style groups and 94 processes. Box area is total wages; colour is AI capability, adoption, or the gap between them.
- **Index:** an AI exposure index and an adoption index (0–100, wage-weighted) for the whole supply chain, each group and each role.
- **Hype vs reality:** a scatter of capability against adoption. Bubble size is average wage.
- **Find your role:** type a job title (e.g. "demand planner") to see where that job's time goes, its exposure index, what the job involves (O*NET), and which AI products touch it.
- **AI products and evidence:** 123 products mapped to 83 processes, plus sourced evidence labelled as independent, news or company-reported.
- **Share:** "Copy link" keeps the current view (country, colours, role, selected process) in the URL. "Download image" saves a PNG of the map with a caption and sources.

Workers and wages: BLS OEWS May 2025 (US); ESDC COPS and Job Bank 2025 (Canada); 2025 Bank of Canada exchange rate. AI scores by Claude Opus 5.5; hand-scored processes are marked as such.

## Layout

- `data/`: tables as CSV. See [data/SCHEMA.md](data/SCHEMA.md). `data/raw/` holds downloads and is git-ignored.
- `scripts/fetch_data.sh`: downloads the public source files.
- `scripts/prepare_data.py`: turns raw files into the generated tables.
- `scripts/validate.py`: schema, key and range checks.
- `scripts/build_site_data.py`: turns the CSVs into `site/data.js`.
- `scripts/score_server.py`: local scoring mode (see below).
- `site/`: the static dashboard (plain HTML, CSS and JS; D3 from a CDN). Publish this folder as-is.

## Rebuild

```bash
./scripts/fetch_data.sh
```

```bash
python3 -I scripts/prepare_data.py && python3 scripts/validate.py && python3 -I scripts/build_site_data.py
```

## Run locally

```bash
python3 -m http.server 8765 --bind 127.0.0.1 --directory site
```

Then open http://localhost:8765.

## Hand-score processes (local scoring mode)

```bash
python3 -I scripts/score_server.py
```

Open http://127.0.0.1:8766. A scoring panel lists your hand-score queue. Pick a process, set capability and adoption (0–10) with a one-line reason, and save. Each save appends a new version to `data/process_scores.csv` (`scored_by=llm+expert`) and rebuilds `site/data.js`. The page then shows the process as "Hand-scored" and the banner counts it.

The server binds to 127.0.0.1, only writes `data/process_scores.csv`, and refuses cross-origin requests. The published static site serves `scoring.js` with the flag off, so the editor never appears there.

## Credits and licences

- US employment and wages: U.S. Bureau of Labor Statistics, OEWS May 2025 (public domain).
- Canadian employment and wages: ESDC COPS and Job Bank. Contains information licensed under the Open Government Licence – Canada.
- Job tasks: O*NET 31.0 Database by the U.S. Department of Labor, Employment and Training Administration (USDOL/ETA), used under CC BY 4.0. This project selected a subset of task statements; USDOL/ETA has not approved, endorsed, or tested these modifications. O*NET® is a trademark of USDOL/ETA.
- NOC 2021–O*NET crosswalk: The Dais (MIT License), adjusted by hand in `data/crosswalk_overrides.csv`.
- Exchange rate: Bank of Canada.
- AI products are examples, not endorsements; product names are trademarks of their owners. SAP module names are used only as reference labels; SAP is not affiliated with this project.
