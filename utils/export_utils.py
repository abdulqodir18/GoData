from __future__ import annotations

import json
from datetime import datetime
from io import BytesIO

import pandas as pd

from utils.validation import combine_validation_violations, validation_results_summary


def _json_default(value):
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable.")


def dataframe_to_csv_bytes(dataframe: pd.DataFrame) -> bytes:
    return dataframe.to_csv(index=False).encode("utf-8")


def dataframe_to_excel_bytes(dataframe: pd.DataFrame) -> bytes:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        dataframe.to_excel(writer, index=False, sheet_name="cleaned_data")
    buffer.seek(0)
    return buffer.getvalue()


def build_transformation_report(
    file_name: str | None,
    original_df: pd.DataFrame | None,
    working_df: pd.DataFrame | None,
    transform_log: list[dict],
    validation_results: list[dict],
) -> dict:
    return {
        "file_name": file_name or "unknown_file",
        "export_timestamp": datetime.now().isoformat(timespec="seconds"),
        "dataset_shape_before": {
            "rows": int(original_df.shape[0]) if original_df is not None else 0,
            "columns": int(original_df.shape[1]) if original_df is not None else 0,
        },
        "dataset_shape_after": {
            "rows": int(working_df.shape[0]) if working_df is not None else 0,
            "columns": int(working_df.shape[1]) if working_df is not None else 0,
        },
        "operations_count": len(transform_log),
        "operations": transform_log,
        "validation_summary": validation_results_summary(validation_results).to_dict(orient="records"),
    }


def transformation_report_to_json_bytes(report: dict) -> bytes:
    return json.dumps(report, indent=2, default=_json_default).encode("utf-8")


def recipe_from_transform_log(transform_log: list[dict]) -> list[dict]:
    return [
        {
            "step_id": entry["step_id"],
            "operation": entry["operation"],
            "columns": entry["affected_columns"],
            "parameters": entry["parameters"],
        }
        for entry in transform_log
    ]


def recipe_to_json_bytes(transform_log: list[dict]) -> bytes:
    recipe = recipe_from_transform_log(transform_log)
    return json.dumps(recipe, indent=2, default=_json_default).encode("utf-8")


def validation_violations_to_csv_bytes(validation_results: list[dict]) -> bytes:
    violations = combine_validation_violations(validation_results)
    if violations.empty:
        return b""
    return violations.to_csv(index=False).encode("utf-8")


def pipeline_snippet_from_transform_log(transform_log: list[dict]) -> str:
    lines = [
        "import pandas as pd",
        "",
        "# Replay the logged GoData workflow below.",
        "df = pd.read_csv('your_input.csv')",
        "",
    ]
    for entry in transform_log:
        lines.append(f"# Step {entry['step_id']}: {entry['operation']}")
        lines.append(f"# Columns: {entry['affected_columns']}")
        lines.append(f"# Parameters: {entry['parameters']}")
        lines.append("")
    lines.append("print(df.head())")
    return "\n".join(lines)


def pipeline_snippet_to_bytes(transform_log: list[dict]) -> bytes:
    return pipeline_snippet_from_transform_log(transform_log).encode("utf-8")
