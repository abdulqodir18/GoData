from __future__ import annotations

from copy import deepcopy
from datetime import datetime

import pandas as pd
import streamlit as st


SESSION_DEFAULTS = {
    "original_df": None,
    "working_df": None,
    "transform_log": [],
    "history": [],
    "validation_results": [],
    "current_file_name": None,
    "uploaded_file_signature": None,
    "chart_state": {},
}


def init_session_state() -> None:
    for key, default_value in SESSION_DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = deepcopy(default_value)


def has_data() -> bool:
    return st.session_state.get("working_df") is not None


def _clear_workflow_state() -> None:
    st.session_state["transform_log"] = []
    st.session_state["history"] = []
    st.session_state["validation_results"] = []
    st.session_state["chart_state"] = {}


def load_dataframe_into_state(
    dataframe: pd.DataFrame,
    file_name: str,
    signature: str | None = None,
) -> None:
    st.session_state["original_df"] = dataframe.copy(deep=True)
    st.session_state["working_df"] = dataframe.copy(deep=True)
    st.session_state["current_file_name"] = file_name
    st.session_state["uploaded_file_signature"] = signature
    _clear_workflow_state()


def reset_working_data() -> bool:
    original_df = st.session_state.get("original_df")
    if original_df is None:
        return False

    st.session_state["working_df"] = original_df.copy(deep=True)
    _clear_workflow_state()
    return True


def push_history_snapshot() -> None:
    working_df = st.session_state.get("working_df")
    if working_df is None:
        return

    history = st.session_state["history"]
    history.append(working_df.copy(deep=True))
    if len(history) > 25:
        history.pop(0)


def _build_log_entry(
    operation: str,
    affected_columns: list[str] | None,
    parameters: dict | None,
    rows_before: int,
    rows_after: int,
) -> dict:
    transform_log = st.session_state["transform_log"]
    return {
        "step_id": len(transform_log) + 1,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "operation": operation,
        "affected_columns": affected_columns or [],
        "parameters": parameters or {},
        "rows_before": rows_before,
        "rows_after": rows_after,
    }


def apply_transformation(
    new_dataframe: pd.DataFrame,
    operation: str,
    affected_columns: list[str] | None = None,
    parameters: dict | None = None,
) -> dict:
    working_df = st.session_state.get("working_df")
    if working_df is None:
        raise ValueError("Load a dataset before applying transformations.")

    push_history_snapshot()
    entry = _build_log_entry(
        operation=operation,
        affected_columns=affected_columns,
        parameters=parameters,
        rows_before=int(working_df.shape[0]),
        rows_after=int(new_dataframe.shape[0]),
    )
    st.session_state["working_df"] = new_dataframe
    st.session_state["transform_log"].append(entry)
    return entry


def undo_last_step() -> bool:
    history = st.session_state.get("history", [])
    if not history:
        return False

    st.session_state["working_df"] = history.pop()
    transform_log = st.session_state.get("transform_log", [])
    if transform_log:
        transform_log.pop()
    return True
