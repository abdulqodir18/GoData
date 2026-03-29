from __future__ import annotations

import numpy as np
import pandas as pd


def _validate_columns(dataframe: pd.DataFrame, columns: list[str]) -> None:
    missing_columns = [column for column in columns if column not in dataframe.columns]
    if missing_columns:
        raise ValueError(f"Columns not found in the dataset: {', '.join(missing_columns)}")


def rename_dataframe_columns(dataframe: pd.DataFrame, rename_map: dict[str, str]) -> pd.DataFrame:
    _validate_columns(dataframe, list(rename_map.keys()))
    new_names = [value for value in rename_map.values() if value]
    if len(new_names) != len(set(new_names)):
        raise ValueError("Renamed columns must remain unique.")
    return dataframe.rename(columns=rename_map).copy()


def drop_selected_columns(dataframe: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    _validate_columns(dataframe, columns)
    if not columns:
        raise ValueError("Select at least one column to drop.")
    return dataframe.drop(columns=columns).copy()


def create_formula_column(
    dataframe: pd.DataFrame,
    new_column_name: str,
    formula_type: str,
    source_column: str,
    other_column: str | None = None,
) -> pd.DataFrame:
    if not new_column_name.strip():
        raise ValueError("Provide a name for the new column.")
    if new_column_name in dataframe.columns:
        raise ValueError("The new column name already exists.")

    _validate_columns(dataframe, [source_column])
    new_dataframe = dataframe.copy()
    source_series = pd.to_numeric(new_dataframe[source_column], errors="coerce")

    if formula_type == "divide_columns":
        if other_column is None:
            raise ValueError("Select a denominator column for division.")
        _validate_columns(dataframe, [other_column])
        denominator = pd.to_numeric(new_dataframe[other_column], errors="coerce")
        zero_count = int((denominator == 0).fillna(False).sum())
        if zero_count > 0:
            raise ValueError(f"Cannot divide by zero. {zero_count} denominator values are zero.")
        new_dataframe[new_column_name] = source_series / denominator
    elif formula_type == "subtract_column_mean":
        new_dataframe[new_column_name] = source_series - source_series.mean()
    elif formula_type == "log_column":
        non_positive_count = int((source_series <= 0).fillna(False).sum())
        if non_positive_count > 0:
            raise ValueError(f"Log transform requires positive values. {non_positive_count} rows are non-positive.")
        new_dataframe[new_column_name] = np.log(source_series)
    else:
        raise ValueError("Unsupported formula type.")

    return new_dataframe


def bin_numeric_column(
    dataframe: pd.DataFrame,
    column: str,
    new_column_name: str,
    bins: int,
    method: str,
) -> pd.DataFrame:
    if bins < 2:
        raise ValueError("Bin count must be at least 2.")
    if not new_column_name.strip():
        raise ValueError("Provide a name for the binned column.")
    if new_column_name in dataframe.columns:
        raise ValueError("The binned column name already exists.")

    _validate_columns(dataframe, [column])
    new_dataframe = dataframe.copy()
    numeric_series = pd.to_numeric(new_dataframe[column], errors="coerce")
    if numeric_series.dropna().nunique() < bins and method == "quantile":
        raise ValueError("Quantile binning needs at least as many unique numeric values as bins.")

    if method == "equal_width":
        binned = pd.cut(numeric_series, bins=bins, duplicates="drop")
    elif method == "quantile":
        binned = pd.qcut(numeric_series, q=bins, duplicates="drop")
    else:
        raise ValueError("Unsupported binning method.")

    new_dataframe[new_column_name] = binned.astype("category")
    return new_dataframe
