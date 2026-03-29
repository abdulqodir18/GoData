from __future__ import annotations

import numpy as np
import pandas as pd


def _validate_columns(dataframe: pd.DataFrame, columns: list[str]) -> None:
    missing_columns = [column for column in columns if column not in dataframe.columns]
    if missing_columns:
        raise ValueError(f"Columns not found in the dataset: {', '.join(missing_columns)}")


def get_missing_summary(dataframe: pd.DataFrame) -> pd.DataFrame:
    summary = pd.DataFrame(
        {
            "column": dataframe.columns,
            "missing_count": dataframe.isna().sum().values,
        }
    )
    summary["missing_pct"] = ((summary["missing_count"] / max(len(dataframe), 1)) * 100).round(2)
    return summary.sort_values(["missing_count", "column"], ascending=[False, True]).reset_index(drop=True)


def drop_rows_with_missing(dataframe: pd.DataFrame, columns: list[str]) -> tuple[pd.DataFrame, int]:
    _validate_columns(dataframe, columns)
    if not columns:
        raise ValueError("Select at least one column to drop rows with missing values.")

    mask = dataframe[columns].isna().any(axis=1)
    removed_rows = int(mask.sum())
    return dataframe.loc[~mask].copy(), removed_rows


def get_columns_above_missing_threshold(dataframe: pd.DataFrame, threshold_pct: float) -> list[str]:
    summary = get_missing_summary(dataframe)
    return summary.loc[summary["missing_pct"] > threshold_pct, "column"].tolist()


def drop_columns_above_missing_threshold(
    dataframe: pd.DataFrame, threshold_pct: float
) -> tuple[pd.DataFrame, list[str]]:
    columns_to_drop = get_columns_above_missing_threshold(dataframe, threshold_pct)
    return dataframe.drop(columns=columns_to_drop).copy(), columns_to_drop


def fill_missing_values(
    dataframe: pd.DataFrame,
    columns: list[str],
    method: str,
    constant_value: str | float | int | None = None,
) -> tuple[pd.DataFrame, dict]:
    _validate_columns(dataframe, columns)
    if not columns:
        raise ValueError("Select at least one column to fill.")

    new_dataframe = dataframe.copy()
    metadata: dict[str, object] = {"method": method, "fill_values": {}}

    if method in {"ffill", "bfill"}:
        if method == "ffill":
            new_dataframe[columns] = new_dataframe[columns].ffill()
        else:
            new_dataframe[columns] = new_dataframe[columns].bfill()
        return new_dataframe, metadata

    for column in columns:
        series = new_dataframe[column]
        if method == "constant":
            fill_value = constant_value
        elif method == "mean":
            if not pd.api.types.is_numeric_dtype(series):
                raise ValueError(f"Column '{column}' must be numeric for mean fill.")
            fill_value = float(series.mean())
        elif method == "median":
            if not pd.api.types.is_numeric_dtype(series):
                raise ValueError(f"Column '{column}' must be numeric for median fill.")
            fill_value = float(series.median())
        elif method in {"mode", "most_frequent"}:
            mode = series.mode(dropna=True)
            if mode.empty:
                raise ValueError(f"Column '{column}' has no non-null values to compute a fill value.")
            fill_value = mode.iloc[0]
        else:
            raise ValueError("Unsupported fill method selected.")

        new_dataframe[column] = series.fillna(fill_value)
        metadata["fill_values"][column] = fill_value

    return new_dataframe, metadata


def find_duplicate_rows(dataframe: pd.DataFrame, subset: list[str] | None = None) -> pd.DataFrame:
    if subset:
        _validate_columns(dataframe, subset)

    duplicate_mask = dataframe.duplicated(subset=subset, keep=False)
    duplicate_rows = dataframe.loc[duplicate_mask].copy()
    if duplicate_rows.empty:
        return duplicate_rows

    comparison_columns = subset or list(dataframe.columns)
    group_keys = duplicate_rows[comparison_columns].astype(str).agg(" | ".join, axis=1)
    duplicate_rows.insert(0, "duplicate_group", pd.factorize(group_keys)[0] + 1)
    return duplicate_rows.sort_values("duplicate_group")


def remove_duplicates(
    dataframe: pd.DataFrame,
    subset: list[str] | None = None,
    keep: str = "first",
) -> tuple[pd.DataFrame, int]:
    if subset:
        _validate_columns(dataframe, subset)

    duplicate_mask = dataframe.duplicated(subset=subset, keep=keep)
    removed_rows = int(duplicate_mask.sum())
    return dataframe.loc[~duplicate_mask].copy(), removed_rows


def clean_numeric_strings(series: pd.Series) -> pd.Series:
    cleaned_series = series.astype(str).str.strip()
    cleaned_series = cleaned_series.replace({"": np.nan, "nan": np.nan, "None": np.nan, "N/A": np.nan})
    cleaned_series = cleaned_series.str.replace(r"\(([^)]+)\)", r"-\1", regex=True)
    cleaned_series = cleaned_series.str.replace(r"[^0-9.\-]", "", regex=True)
    cleaned_series = cleaned_series.replace({"": np.nan, "-": np.nan, ".": np.nan})
    return cleaned_series


def convert_columns_to_numeric(
    dataframe: pd.DataFrame,
    columns: list[str],
    strip_characters: bool = True,
) -> tuple[pd.DataFrame, dict[str, int]]:
    _validate_columns(dataframe, columns)
    new_dataframe = dataframe.copy()
    failure_counts: dict[str, int] = {}

    for column in columns:
        source_series = new_dataframe[column]
        candidate_series = clean_numeric_strings(source_series) if strip_characters else source_series
        converted_series = pd.to_numeric(candidate_series, errors="coerce")
        failures = int(source_series.notna().sum() - converted_series.notna().sum())
        new_dataframe[column] = converted_series
        failure_counts[column] = failures

    return new_dataframe, failure_counts


def convert_columns_to_category(dataframe: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    _validate_columns(dataframe, columns)
    new_dataframe = dataframe.copy()
    for column in columns:
        new_dataframe[column] = new_dataframe[column].astype("category")
    return new_dataframe


def convert_columns_to_datetime(
    dataframe: pd.DataFrame,
    columns: list[str],
    date_format: str | None = None,
) -> tuple[pd.DataFrame, dict[str, int]]:
    _validate_columns(dataframe, columns)
    new_dataframe = dataframe.copy()
    failure_counts: dict[str, int] = {}

    for column in columns:
        converted_series = pd.to_datetime(
            new_dataframe[column],
            format=date_format or None,
            errors="coerce",
        )
        failures = int(new_dataframe[column].notna().sum() - converted_series.notna().sum())
        new_dataframe[column] = converted_series
        failure_counts[column] = failures

    return new_dataframe, failure_counts


def trim_whitespace(dataframe: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    _validate_columns(dataframe, columns)
    new_dataframe = dataframe.copy()
    for column in columns:
        new_dataframe[column] = new_dataframe[column].map(lambda value: value.strip() if isinstance(value, str) else value)
    return new_dataframe


def standardize_case(dataframe: pd.DataFrame, columns: list[str], case_style: str) -> pd.DataFrame:
    _validate_columns(dataframe, columns)
    new_dataframe = dataframe.copy()

    def _format_value(value: object) -> object:
        if not isinstance(value, str):
            return value
        if case_style == "lower":
            return value.lower()
        if case_style == "title":
            return value.title()
        if case_style == "upper":
            return value.upper()
        raise ValueError("Unsupported case style.")

    for column in columns:
        new_dataframe[column] = new_dataframe[column].map(_format_value)
    return new_dataframe


def map_categorical_values(
    dataframe: pd.DataFrame,
    column: str,
    mapping: dict,
    group_unmapped_to_other: bool = False,
) -> pd.DataFrame:
    _validate_columns(dataframe, [column])
    new_dataframe = dataframe.copy()

    def _map_value(value: object) -> object:
        if pd.isna(value):
            return value
        if value in mapping:
            replacement = mapping[value]
            return value if replacement in ("", None) else replacement
        if group_unmapped_to_other:
            return "Other"
        return value

    new_dataframe[column] = new_dataframe[column].map(_map_value)
    return new_dataframe


def group_rare_categories(
    dataframe: pd.DataFrame,
    column: str,
    threshold: float,
    threshold_kind: str = "count",
) -> tuple[pd.DataFrame, list[object]]:
    _validate_columns(dataframe, [column])
    new_dataframe = dataframe.copy()
    value_counts = new_dataframe[column].value_counts(dropna=False)

    if threshold_kind == "count":
        rare_values = value_counts[value_counts < threshold].index.tolist()
    elif threshold_kind == "percent":
        proportions = value_counts / max(len(new_dataframe), 1)
        rare_values = proportions[proportions < threshold].index.tolist()
    else:
        raise ValueError("Unsupported rare category threshold type.")

    rare_values = [value for value in rare_values if pd.notna(value)]
    new_dataframe[column] = new_dataframe[column].map(lambda value: "Other" if value in rare_values else value)
    return new_dataframe, rare_values


def one_hot_encode_columns(dataframe: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    _validate_columns(dataframe, columns)
    return pd.get_dummies(dataframe, columns=columns, dummy_na=False)


def describe_outliers(
    dataframe: pd.DataFrame,
    column: str,
    method: str,
    iqr_multiplier: float = 1.5,
    z_threshold: float = 3.0,
) -> dict:
    _validate_columns(dataframe, [column])
    numeric_series = pd.to_numeric(dataframe[column], errors="coerce")
    if numeric_series.dropna().empty:
        raise ValueError(f"Column '{column}' does not contain numeric data.")

    if method == "iqr":
        q1 = numeric_series.quantile(0.25)
        q3 = numeric_series.quantile(0.75)
        iqr = q3 - q1
        lower_bound = q1 - (iqr_multiplier * iqr)
        upper_bound = q3 + (iqr_multiplier * iqr)
    elif method == "zscore":
        mean_value = numeric_series.mean()
        std_value = numeric_series.std(ddof=0)
        if pd.isna(std_value) or std_value == 0:
            lower_bound = mean_value
            upper_bound = mean_value
        else:
            lower_bound = mean_value - (z_threshold * std_value)
            upper_bound = mean_value + (z_threshold * std_value)
    else:
        raise ValueError("Unsupported outlier detection method.")

    mask = ((numeric_series < lower_bound) | (numeric_series > upper_bound)).fillna(False)
    return {
        "column": column,
        "method": method,
        "lower_bound": float(lower_bound),
        "upper_bound": float(upper_bound),
        "outlier_count": int(mask.sum()),
        "outlier_mask": mask,
    }


def cap_outliers(
    dataframe: pd.DataFrame,
    column: str,
    method: str,
    iqr_multiplier: float = 1.5,
    z_threshold: float = 3.0,
) -> tuple[pd.DataFrame, int]:
    summary = describe_outliers(
        dataframe=dataframe,
        column=column,
        method=method,
        iqr_multiplier=iqr_multiplier,
        z_threshold=z_threshold,
    )
    new_dataframe = dataframe.copy()
    numeric_series = pd.to_numeric(new_dataframe[column], errors="coerce")
    new_dataframe[column] = numeric_series.clip(lower=summary["lower_bound"], upper=summary["upper_bound"])
    return new_dataframe, summary["outlier_count"]


def remove_outlier_rows(
    dataframe: pd.DataFrame,
    column: str,
    method: str,
    iqr_multiplier: float = 1.5,
    z_threshold: float = 3.0,
) -> tuple[pd.DataFrame, int]:
    summary = describe_outliers(
        dataframe=dataframe,
        column=column,
        method=method,
        iqr_multiplier=iqr_multiplier,
        z_threshold=z_threshold,
    )
    return dataframe.loc[~summary["outlier_mask"]].copy(), summary["outlier_count"]


def scale_numeric_columns(
    dataframe: pd.DataFrame,
    columns: list[str],
    method: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    _validate_columns(dataframe, columns)
    new_dataframe = dataframe.copy()
    before_stats: list[dict[str, float | str]] = []
    after_stats: list[dict[str, float | str]] = []

    for column in columns:
        numeric_series = pd.to_numeric(new_dataframe[column], errors="coerce")
        if numeric_series.dropna().empty:
            raise ValueError(f"Column '{column}' does not contain numeric values.")

        before_stats.append(
            {
                "column": column,
                "min": float(numeric_series.min()),
                "max": float(numeric_series.max()),
                "mean": float(numeric_series.mean()),
                "std": float(numeric_series.std(ddof=0)),
            }
        )

        if method == "minmax":
            min_value = numeric_series.min()
            max_value = numeric_series.max()
            if min_value == max_value:
                scaled_series = numeric_series * 0
            else:
                scaled_series = (numeric_series - min_value) / (max_value - min_value)
        elif method == "zscore":
            mean_value = numeric_series.mean()
            std_value = numeric_series.std(ddof=0)
            if std_value == 0 or pd.isna(std_value):
                scaled_series = numeric_series * 0
            else:
                scaled_series = (numeric_series - mean_value) / std_value
        else:
            raise ValueError("Unsupported scaling method.")

        new_dataframe[column] = scaled_series
        after_stats.append(
            {
                "column": column,
                "min": float(scaled_series.min()),
                "max": float(scaled_series.max()),
                "mean": float(scaled_series.mean()),
                "std": float(scaled_series.std(ddof=0)),
            }
        )

    return new_dataframe, pd.DataFrame(before_stats), pd.DataFrame(after_stats)
