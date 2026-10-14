#!/usr/bin/env bash
# Download the public source files into data/raw/ (about 60 MB). Re-run to refresh.
#
# BLS blocks scripted downloads, so the two US files in data/raw/bls/ are pulled by hand:
# open https://data.bls.gov/oes/#/area/0000000/2025 in a browser, then in the dev-tools console POST
#   /OESServices/prefilter/table  {areaCode:"0000000", industryCode:"000000", year:"2025", tableSuffix:"pub", userId:"", pwd:""}
# and keep datatypeCode "01" (employment) and "04" (mean annual wage) per formattedOccupationCode.
# Save them as oews_national_may2025.csv (soc_code,employment,mean_annual_wage,footnote; listed occupations)
# and oews_national_may2025_employment_all.csv (soc_code,employment; every occupation).
set -euo pipefail
cd "$(dirname "$0")/../data/raw"
mkdir -p onet jobbank cops dais boc
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"
ONET=https://www.onetcenter.org/dl_files/database/db_31_0_csv
OPEN=https://open.canada.ca/data/dataset

curl -sSfL -A "$UA" -o onet/task_statements.csv "$ONET/task_statements.csv"
curl -sSfL -A "$UA" -o onet/task_ratings.csv "$ONET/task_ratings.csv"
curl -sSfL -A "$UA" -o onet/occupation_data.csv "$ONET/occupation_data.csv"
curl -sSfL -o jobbank/wages_2025.csv \
  "$OPEN/adad580f-76b0-4502-bd05-20c125de9116/resource/9da94d63-b178-4a64-aeb3-b6a3bd721ad2/download/2a71-das-wage2025opendata-esdc-all-19nov2025-vf.csv"
curl -sSfL -o cops/employment_2024_2033_noc2021.csv \
  "$OPEN/e80851b8-de68-43bd-a85c-c72e1b3a3890/resource/da1135c5-a1df-4a07-a81e-de308ae6cce6/download/employment_emploi_2024_2033_noc2021.csv"
curl -sSfL -o dais/noc2021_onet26.csv \
  "https://raw.githubusercontent.com/BrookfieldIIE/NOC_ONet_Crosswalk/master/noc2021_onet26.csv"
curl -sSfL -o boc/fx_annual_usdcad.json \
  "https://www.bankofcanada.ca/valet/observations/FXAUSDCAD/json?recent=6"
echo "Downloaded. Next: python3 -I scripts/prepare_data.py"
