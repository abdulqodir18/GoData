from __future__ import annotations

from datetime import datetime

import pandas as pd


def _base_result(rule_name: str, rule_type: str, column: str, violations: pd.DataFrame) -> dict:
    return {
        "rule_name": rule_name,
        "rule_type": rule_type,
        "column": column,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "violation_count": int(len(violations)),
        "violations": violations.reset_index().rename(columns={"index": "row_index"}),
    }


def run_numeric_range_rule(
    dataframe: pd.DataFrame,
    column: str,
    minimum: float | None = None,
    maximum: float | None = None,
    rule_name: str = "numeric_range",
) -> dict:
    if minimum is None and maximum is None:
        raise ValueError("Set at least a minimum or maximum value for the numeric range rule.")

    numeric_series = pd.to_numeric(dataframe[column], errors="coerce")
    violation_mask = pd.Series(False, index=dataframe.index)
    reasons: list[str] = []

    if minimum is not None:
        below_min = numeric_series < minimum
        violation_mask = violation_mask | below_min.fillna(False)
        reasons.append(f"below {minimum}")
    if maximum is not None:
        above_max = numeric_series > maximum
        violation_mask = violation_mask | above_max.fillna(False)
        reasons.append(f"above {maximum}")

    violations = dataframe.loc[violation_mask, [column]].copy()
    violations["violation_reason"] = " or ".join(reasons)
    return _base_result(rule_name, "numeric_range", column, violations)


def run_allowed_categories_rule(
    dataframe: pd.DataFrame,
    column: str,
    allowed_values: list[object],
    rule_name: str = "allowed_categories",
) -> dict:
    if not allowed_values:
        raise ValueError("Choose at least one allowed category.")

    stringified_series = dataframe[column].astype(str)
    violation_mask = (~stringified_series.isin([str(value) for value in allowed_values])) & dataframe[column].notna()
    violations = dataframe.loc[violation_mask, [column]].copy()
    violations["violation_reason"] = "value not in allowed set"
    return _base_result(rule_name, "allowed_categories", column, violations)


def run_non_null_rule(
    dataframe: pd.DataFrame,
    column: str,
    rule_name: str = "non_null",
) -> dict:
    violation_mask = dataframe[column].isna()
    violations = dataframe.loc[violation_mask, [column]].copy()
    violations["violation_reason"] = "null value"
    return _base_result(rule_name, "non_null", column, violations)


def run_validation_rule(dataframe: pd.DataFrame, rule_type: str, **kwargs) -> dict:
    if rule_type == "numeric_range":
        return run_numeric_range_rule(dataframe=dataframe, **kwargs)
    if rule_type == "allowed_categories":
        return run_allowed_categories_rule(dataframe=dataframe, **kwargs)
    if rule_type == "non_null":
        return run_non_null_rule(dataframe=dataframe, **kwargs)
    raise ValueError("Unsupported validation rule type.")


def validation_results_summary(results: list[dict]) -> pd.DataFrame:
    if not results:
        return pd.DataFrame(columns=["rule_name", "rule_type", "column", "timestamp", "violation_count"])

    return pd.DataFrame(
        [
            {
                "rule_name": result["rule_name"],
                "rule_type": result["rule_type"],
                "column": result["column"],
                "timestamp": result["timestamp"],
                "violation_count": result["violation_count"],
            }
            for result in results
        ]
    )


def combine_validation_violations(results: list[dict]) -> pd.DataFrame:
    if not results:
        return pd.DataFrame()

    frames: list[pd.DataFrame] = []
    for result in results:
        violations = result["violations"].copy()
        if violations.empty:
            continue
        violations.insert(0, "rule_name", result["rule_name"])
        violations.insert(1, "rule_type", result["rule_type"])
        frames.append(violations)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)
