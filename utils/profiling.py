from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st


def _categorical_top_value(series: pd.Series) -> str:
    non_null_series = series.dropna()
    if non_null_series.empty:
        return "N/A"
    mode = non_null_series.mode(dropna=True)
    if mode.empty:
        return "N/A"
    return str(mode.iloc[0])


@st.cache_data(show_spinner=False)
def build_profile(dataframe: pd.DataFrame) -> dict:
    rows, columns = dataframe.shape
    duplicate_count = int(dataframe.duplicated().sum())

    dtype_frame = pd.DataFrame(
        {
            "column": dataframe.columns,
            "dtype": [str(dtype) for dtype in dataframe.dtypes],
            "non_null": dataframe.notna().sum().values,
            "unique_values": dataframe.nunique(dropna=False).values,
        }
    )

    missing_summary = pd.DataFrame(
        {
            "column": dataframe.columns,
            "missing_count": dataframe.isna().sum().values,
        }
    )
    missing_summary["missing_pct"] = ((missing_summary["missing_count"] / max(rows, 1)) * 100).round(2)
    missing_summary = missing_summary.sort_values(["missing_count", "column"], ascending=[False, True]).reset_index(drop=True)

    numeric_columns = dataframe.select_dtypes(include=np.number).columns.tolist()
    numeric_summary = pd.DataFrame()
    if numeric_columns:
        numeric_summary = dataframe[numeric_columns].describe().transpose().reset_index()
        numeric_summary = numeric_summary.rename(columns={"index": "column"})

    categorical_columns = [column for column in dataframe.columns if column not in numeric_columns]
    categorical_summary = pd.DataFrame()
    if categorical_columns:
        categorical_summary = pd.DataFrame(
            {
                "column": categorical_columns,
                "unique_values": [dataframe[column].nunique(dropna=False) for column in categorical_columns],
                "top_value": [_categorical_top_value(dataframe[column]) for column in categorical_columns],
                "missing_count": [int(dataframe[column].isna().sum()) for column in categorical_columns],
            }
        )

    return {
        "rows": rows,
        "columns": columns,
        "dtypes": dtype_frame,
        "missing_summary": missing_summary,
        "numeric_summary": numeric_summary,
        "categorical_summary": categorical_summary,
        "duplicate_count": duplicate_count,
        "preview": dataframe.head(15),
    }
