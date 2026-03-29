from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import pandas as pd
import streamlit as st


SUPPORTED_EXTENSIONS = (".csv", ".xlsx", ".json")


def _make_columns_unique(columns: list[str]) -> list[str]:
    counts: dict[str, int] = {}
    unique_columns: list[str] = []
    for column in columns:
        base_name = str(column)
        if base_name not in counts:
            counts[base_name] = 0
            unique_columns.append(base_name)
            continue
        counts[base_name] += 1
        unique_columns.append(f"{base_name}_{counts[base_name]}")
    return unique_columns


def _normalize_dataframe(dataframe: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(dataframe, pd.DataFrame):
        raise ValueError("The uploaded file could not be converted into a tabular dataset.")

    dataframe = dataframe.copy()
    dataframe.columns = _make_columns_unique([str(column) for column in dataframe.columns])
    return dataframe


def _read_json(file_bytes: bytes) -> pd.DataFrame:
    try:
        return pd.read_json(BytesIO(file_bytes))
    except ValueError:
        pass

    try:
        payload = json.loads(file_bytes.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("The JSON file is not valid JSON.") from exc

    if isinstance(payload, dict):
        list_like_values = [value for value in payload.values() if isinstance(value, list)]
        if list_like_values:
            return pd.json_normalize(list_like_values[0])
        return pd.json_normalize([payload])
    if isinstance(payload, list):
        return pd.json_normalize(payload)

    raise ValueError("The JSON structure is unsupported. Use a list of records or an object containing records.")


def _load_dataframe_from_bytes(file_name: str, file_bytes: bytes) -> pd.DataFrame:
    extension = Path(file_name).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise ValueError("Unsupported file type. Please upload a CSV, XLSX, or JSON file.")

    try:
        if extension == ".csv":
            dataframe = pd.read_csv(BytesIO(file_bytes))
        elif extension == ".xlsx":
            dataframe = pd.read_excel(BytesIO(file_bytes))
        else:
            dataframe = _read_json(file_bytes)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Could not read {file_name}. Please verify the file format and try again.") from exc

    dataframe = _normalize_dataframe(dataframe)
    if dataframe.empty:
        raise ValueError("The file loaded successfully but contains no rows.")
    return dataframe


@st.cache_data(show_spinner=False)
def load_dataframe(file_name: str, file_bytes: bytes) -> pd.DataFrame:
    return _load_dataframe_from_bytes(file_name=file_name, file_bytes=file_bytes)


@st.cache_data(show_spinner=False)
def load_sample_dataframe(file_path: str) -> pd.DataFrame:
    path = Path(file_path)
    return _load_dataframe_from_bytes(file_name=path.name, file_bytes=path.read_bytes())
