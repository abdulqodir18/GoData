# GoData

GoData is a Streamlit mini data preparation studio for coursework submission. It supports dataset upload, profiling, interactive cleaning and transformation, chart building, cleaned-data export, transformation-report export, and recipe-style workflow replay.

## Supported inputs

- CSV
- Excel `.xlsx`
- JSON

## Core workflow

1. Upload a dataset or load a bundled sample dataset.
2. Inspect shape, columns, dtypes, summary statistics, missing values, and duplicates.
3. Clean and transform the working dataframe on the preparation page.
4. Build charts from the transformed data on the visualization page.
5. Export cleaned data, the transformation report, the JSON recipe, and validation violations.

## Project structure

```text
GoData/
├── app.py
├── requirements.txt
├── README.md
├── AI_USAGE.md
├── sample_data/
│   ├── dirty_sales.csv
│   ├── dirty_operations.xlsx
│   └── dirty_customers.json
├── outputs/
│   ├── example_cleaned_sales.csv
│   ├── example_recipe.json
│   ├── example_transformation_report.json
│   └── example_validation_violations.csv
├── prompts_used/
│   ├── 001_coursework_brief.md
│   ├── 002_development_notes.md
│   └── README.md
├── utils/
│   ├── __init__.py
│   ├── charts.py
│   ├── cleaning.py
│   ├── export_utils.py
│   ├── loaders.py
│   ├── profiling.py
│   ├── state.py
│   ├── transforms.py
│   └── validation.py
└── assets/
    └── demo_script.md
```

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run locally

```bash
streamlit run app.py
```

## Streamlit URL
```
https://dwv21945.streamlit.app/
```