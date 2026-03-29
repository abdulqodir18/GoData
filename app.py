from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

from utils.charts import build_chart, filter_dataframe
from utils.cleaning import (
    cap_outliers,
    convert_columns_to_category,
    convert_columns_to_datetime,
    convert_columns_to_numeric,
    describe_outliers,
    drop_columns_above_missing_threshold,
    drop_rows_with_missing,
    fill_missing_values,
    find_duplicate_rows,
    get_columns_above_missing_threshold,
    get_missing_summary,
    group_rare_categories,
    map_categorical_values,
    one_hot_encode_columns,
    remove_duplicates,
    remove_outlier_rows,
    scale_numeric_columns,
    standardize_case,
    trim_whitespace,
)
from utils.export_utils import (
    build_transformation_report,
    dataframe_to_csv_bytes,
    dataframe_to_excel_bytes,
    pipeline_snippet_to_bytes,
    recipe_to_json_bytes,
    transformation_report_to_json_bytes,
    validation_violations_to_csv_bytes,
)
from utils.loaders import SUPPORTED_EXTENSIONS, load_dataframe, load_sample_dataframe
from utils.profiling import build_profile
from utils.state import (
    apply_transformation,
    has_data,
    init_session_state,
    load_dataframe_into_state,
    reset_working_data,
    undo_last_step,
)
from utils.transforms import (
    bin_numeric_column,
    create_formula_column,
    drop_selected_columns,
    rename_dataframe_columns,
)
from utils.validation import (
    combine_validation_violations,
    run_validation_rule,
    validation_results_summary,
)


APP_ROOT = Path(__file__).parent
SAMPLE_DATA_DIR = APP_ROOT / "sample_data"
SUPPORTED_UPLOAD_TYPES = [extension.replace(".", "") for extension in SUPPORTED_EXTENSIONS]


st.set_page_config(page_title="GoData", layout="wide")
init_session_state()


def _log_table(log_entries: list[dict]) -> pd.DataFrame:
    if not log_entries:
        return pd.DataFrame(
            columns=["step_id", "timestamp", "operation", "affected_columns", "parameters", "rows_before", "rows_after"]
        )

    return pd.DataFrame(
        [
            {
                "step_id": entry["step_id"],
                "timestamp": entry["timestamp"],
                "operation": entry["operation"],
                "affected_columns": ", ".join(map(str, entry["affected_columns"])),
                "parameters": json.dumps(entry["parameters"], default=str),
                "rows_before": entry["rows_before"],
                "rows_after": entry["rows_after"],
            }
            for entry in log_entries
        ]
    )


def _safe_preview(dataframe: pd.DataFrame | None, columns: list[str] | None = None, rows: int = 10) -> pd.DataFrame:
    if dataframe is None or dataframe.empty:
        return pd.DataFrame()
    if columns:
        available_columns = [column for column in columns if column in dataframe.columns]
        if available_columns:
            return dataframe[available_columns].head(rows)
    return dataframe.head(rows)


def _parse_optional_float(raw_value: str, label: str) -> float | None:
    raw_value = raw_value.strip()
    if not raw_value:
        return None
    try:
        return float(raw_value)
    except ValueError as exc:
        raise ValueError(f"{label} must be a numeric value.") from exc


def _load_uploaded_file(uploaded_file) -> bool:
    if uploaded_file is None:
        return False

    file_bytes = uploaded_file.getvalue()
    signature = f"{uploaded_file.name}:{len(file_bytes)}:{hashlib.md5(file_bytes).hexdigest()}"
    if st.session_state.get("uploaded_file_signature") == signature:
        return False

    dataframe = load_dataframe(uploaded_file.name, file_bytes)
    load_dataframe_into_state(dataframe=dataframe, file_name=uploaded_file.name, signature=signature)
    return True


def _load_sample_file(sample_name: str) -> None:
    sample_path = SAMPLE_DATA_DIR / sample_name
    dataframe = load_sample_dataframe(str(sample_path))
    signature = f"sample:{sample_name}:{sample_path.stat().st_size}"
    load_dataframe_into_state(dataframe=dataframe, file_name=sample_name, signature=signature)


def _numeric_columns(dataframe: pd.DataFrame) -> list[str]:
    return dataframe.select_dtypes(include=np.number).columns.tolist()


def _categorical_columns(dataframe: pd.DataFrame) -> list[str]:
    return [
        column
        for column in dataframe.columns
        if pd.api.types.is_object_dtype(dataframe[column]) or pd.api.types.is_categorical_dtype(dataframe[column])
    ]


def _render_before_after(before_df: pd.DataFrame, after_df: pd.DataFrame, label_before: str, label_after: str) -> None:
    left_column, right_column = st.columns(2)
    with left_column:
        st.caption(label_before)
        st.dataframe(before_df, use_container_width=True)
    with right_column:
        st.caption(label_after)
        st.dataframe(after_df, use_container_width=True)


def _show_state_actions() -> None:
    with st.sidebar:
        st.title("GoData")
        st.caption("Mini data preparation studio")
        page = st.radio(
            "Navigate",
            [
                "Upload & Overview",
                "Cleaning & Preparation Studio",
                "Visualization Builder",
                "Export & Report",
            ],
        )

        if has_data():
            working_df = st.session_state["working_df"]
            st.divider()
            st.caption(f"Current file: {st.session_state.get('current_file_name', 'Unknown')}")
            st.metric("Rows", int(working_df.shape[0]))
            st.metric("Columns", int(working_df.shape[1]))
            st.metric("Logged steps", len(st.session_state["transform_log"]))

            if st.button("Undo last step", use_container_width=True, disabled=not st.session_state["history"]):
                if undo_last_step():
                    st.success("Reverted the latest transformation.")
                    st.rerun()

            if st.button("Reset all transformations", use_container_width=True):
                reset_working_data()
                st.success("Restored the working dataset from the original upload.")
                st.rerun()

        return page


def _render_upload_page() -> None:
    st.header("Upload & Overview")
    st.write(
        "Load a dataset, inspect the current working copy, and reset the session when you want to start the workflow again."
    )

    upload_column, sample_column = st.columns(2)
    with upload_column:
        uploaded_file = st.file_uploader(
            "Upload CSV, XLSX, or JSON",
            type=SUPPORTED_UPLOAD_TYPES,
            help="The app reads CSV, Excel (.xlsx), and JSON files.",
        )
        if uploaded_file is not None:
            try:
                if _load_uploaded_file(uploaded_file):
                    st.success(f"Loaded {uploaded_file.name} into the working studio.")
            except ValueError as exc:
                st.error(str(exc))

    with sample_column:
        sample_files = sorted([path.name for path in SAMPLE_DATA_DIR.iterdir() if path.is_file()])
        sample_choice = st.selectbox("Or load one of the included sample datasets", ["Select a sample"] + sample_files)
        if st.button("Load sample dataset", disabled=sample_choice == "Select a sample"):
            try:
                _load_sample_file(sample_choice)
                st.success(f"Loaded sample dataset: {sample_choice}")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    if st.button("Reset session", disabled=not has_data()):
        reset_working_data()
        st.success("Session reset to the original uploaded dataset.")
        st.rerun()

    if not has_data():
        st.info("Upload a dataset or load a sample file to start.")
        return

    dataframe = st.session_state["working_df"]
    profile = build_profile(dataframe)

    metric_columns = st.columns(4)
    metric_columns[0].metric("Rows", profile["rows"])
    metric_columns[1].metric("Columns", profile["columns"])
    metric_columns[2].metric("Duplicate rows", profile["duplicate_count"])
    metric_columns[3].metric("Columns box", profile["columns"])

    st.subheader("Dataset Preview")
    st.dataframe(profile["preview"], use_container_width=True)

    st.subheader("Column Names")
    st.dataframe(pd.DataFrame({"column_name": dataframe.columns}), use_container_width=True, height=240)

    left_column, right_column = st.columns(2)
    with left_column:
        st.subheader("Inferred dtypes")
        st.dataframe(profile["dtypes"], use_container_width=True, height=320)
    with right_column:
        st.subheader("Missing values by column")
        st.dataframe(profile["missing_summary"], use_container_width=True, height=320)

    summary_tabs = st.tabs(["Numeric Summary", "Categorical Summary"])
    with summary_tabs[0]:
        if profile["numeric_summary"].empty:
            st.info("No numeric columns were detected yet.")
        else:
            st.dataframe(profile["numeric_summary"], use_container_width=True)
    with summary_tabs[1]:
        if profile["categorical_summary"].empty:
            st.info("No categorical columns were detected yet.")
        else:
            st.dataframe(profile["categorical_summary"], use_container_width=True)


def _render_missing_values_tab(dataframe: pd.DataFrame) -> None:
    st.subheader("Missing values")
    st.dataframe(get_missing_summary(dataframe), use_container_width=True, height=260)

    action = st.radio(
        "Choose a missing-value action",
        ["Drop rows", "Drop columns above threshold", "Fill missing values"],
        horizontal=True,
        key="missing_action",
    )

    if action == "Drop rows":
        columns = st.multiselect("Columns to inspect for missing values", dataframe.columns.tolist(), key="drop_missing_columns")
        if columns:
            candidate_df, rows_removed = drop_rows_with_missing(dataframe, columns)
            impacted_rows = dataframe.loc[dataframe[columns].isna().any(axis=1), columns].head(10)
            st.metric("Rows that would be removed", rows_removed)
            _render_before_after(impacted_rows, _safe_preview(candidate_df, columns), "Rows before removal", "Dataset after removal")
            if st.button("Apply row drop", key="apply_drop_missing_rows"):
                entry = apply_transformation(
                    candidate_df,
                    operation="drop_missing_rows",
                    affected_columns=columns,
                    parameters={"columns": columns, "rows_removed": rows_removed},
                )
                st.success(f"Applied step {entry['step_id']}: dropped {rows_removed} rows with missing values.")
                st.rerun()

    elif action == "Drop columns above threshold":
        threshold = st.slider("Drop columns if missing percentage is greater than", 0, 100, 30, 5, key="missing_threshold")
        columns_to_drop = get_columns_above_missing_threshold(dataframe, threshold)
        st.write("Columns that would be removed:", columns_to_drop if columns_to_drop else "None")
        if columns_to_drop:
            candidate_df, _ = drop_columns_above_missing_threshold(dataframe, threshold)
            _render_before_after(
                _safe_preview(dataframe, columns_to_drop),
                _safe_preview(candidate_df),
                "Columns before drop",
                "Dataset after drop",
            )
            if st.button("Apply threshold drop", key="apply_drop_missing_cols"):
                entry = apply_transformation(
                    candidate_df,
                    operation="drop_columns_missing_threshold",
                    affected_columns=columns_to_drop,
                    parameters={"threshold_pct": threshold},
                )
                st.success(f"Applied step {entry['step_id']}: dropped {len(columns_to_drop)} columns.")
                st.rerun()
        else:
            st.info("No columns exceed the selected missing-value threshold.")

    else:
        columns = st.multiselect("Columns to fill", dataframe.columns.tolist(), key="fill_missing_columns")
        method = st.selectbox(
            "Fill method",
            ["constant", "mean", "median", "mode", "most_frequent", "ffill", "bfill"],
            key="fill_method",
        )
        constant_value = None
        if method == "constant":
            constant_value = st.text_input("Constant fill value", key="constant_fill_value")

        if columns:
            try:
                candidate_df, metadata = fill_missing_values(
                    dataframe=dataframe,
                    columns=columns,
                    method=method,
                    constant_value=constant_value,
                )
                impacted_rows = dataframe.loc[dataframe[columns].isna().any(axis=1), columns].head(10)
                st.write(f"Columns affected: {', '.join(columns)}")
                st.write(f"Fill method: {method}")
                _render_before_after(
                    impacted_rows,
                    candidate_df.loc[impacted_rows.index, columns] if not impacted_rows.empty else _safe_preview(candidate_df, columns),
                    "Before fill",
                    "After fill",
                )
                if st.button("Apply fill", key="apply_fill_missing"):
                    entry = apply_transformation(
                        candidate_df,
                        operation="fill_missing",
                        affected_columns=columns,
                        parameters={"method": method, "fill_details": metadata["fill_values"]},
                    )
                    st.success(f"Applied step {entry['step_id']}: filled missing values with {method}.")
                    st.rerun()
            except ValueError as exc:
                st.error(str(exc))


def _render_duplicates_tab(dataframe: pd.DataFrame) -> None:
    st.subheader("Duplicates")
    st.metric("Full-row duplicates detected", int(dataframe.duplicated().sum()))

    subset_columns = st.multiselect(
        "Optional duplicate key columns",
        dataframe.columns.tolist(),
        key="duplicate_subset_columns",
        help="Leave empty to detect full-row duplicates.",
    )
    duplicate_rows = find_duplicate_rows(dataframe, subset=subset_columns or None)
    st.metric("Duplicate rows shown below", int(len(duplicate_rows)))

    if duplicate_rows.empty:
        st.info("No duplicates matched the selected key.")
        return

    st.dataframe(duplicate_rows.head(100), use_container_width=True, height=280)
    keep = st.radio("Keep which duplicate record?", ["first", "last"], horizontal=True, key="duplicate_keep")
    candidate_df, removed_rows = remove_duplicates(dataframe, subset=subset_columns or None, keep=keep)
    st.write(f"Rows that would be removed: {removed_rows}")

    if st.button("Remove duplicates", key="apply_remove_duplicates"):
        entry = apply_transformation(
            candidate_df,
            operation="drop_duplicates",
            affected_columns=subset_columns,
            parameters={"subset": subset_columns or "all_columns", "keep": keep, "rows_removed": removed_rows},
        )
        st.success(f"Applied step {entry['step_id']}: removed {removed_rows} duplicate rows.")
        st.rerun()


def _render_dtype_tab(dataframe: pd.DataFrame) -> None:
    st.subheader("Data types and parsing")
    columns = st.multiselect("Columns to convert", dataframe.columns.tolist(), key="dtype_columns")
    target_type = st.selectbox("Target type", ["numeric", "category", "datetime"], key="dtype_target_type")

    if not columns:
        st.info("Choose one or more columns to preview a conversion.")
        return

    try:
        if target_type == "numeric":
            strip_characters = st.checkbox("Strip commas, currency symbols, percent signs, and spaces first", value=True)
            candidate_df, failure_counts = convert_columns_to_numeric(dataframe, columns, strip_characters=strip_characters)
            st.dataframe(pd.DataFrame({"column": list(failure_counts), "failed_conversions": list(failure_counts.values())}))
            _render_before_after(
                _safe_preview(dataframe, columns),
                _safe_preview(candidate_df, columns),
                "Before conversion",
                "After conversion",
            )
            if st.button("Apply numeric conversion", key="apply_dtype_numeric"):
                entry = apply_transformation(
                    candidate_df,
                    operation="convert_to_numeric",
                    affected_columns=columns,
                    parameters={"strip_characters": strip_characters, "failed_conversions": failure_counts},
                )
                st.success(f"Applied step {entry['step_id']}: converted columns to numeric.")
                st.rerun()

        elif target_type == "category":
            candidate_df = convert_columns_to_category(dataframe, columns)
            _render_before_after(
                _safe_preview(dataframe, columns),
                _safe_preview(candidate_df, columns),
                "Before conversion",
                "After conversion",
            )
            if st.button("Apply category conversion", key="apply_dtype_category"):
                entry = apply_transformation(
                    candidate_df,
                    operation="convert_to_category",
                    affected_columns=columns,
                    parameters={"target_type": "category"},
                )
                st.success(f"Applied step {entry['step_id']}: converted columns to category.")
                st.rerun()

        else:
            date_format = st.text_input("Optional datetime format", placeholder="%Y-%m-%d", key="datetime_format")
            candidate_df, failure_counts = convert_columns_to_datetime(dataframe, columns, date_format=date_format or None)
            st.dataframe(pd.DataFrame({"column": list(failure_counts), "failed_conversions": list(failure_counts.values())}))
            _render_before_after(
                _safe_preview(dataframe, columns),
                _safe_preview(candidate_df, columns),
                "Before conversion",
                "After conversion",
            )
            if st.button("Apply datetime conversion", key="apply_dtype_datetime"):
                entry = apply_transformation(
                    candidate_df,
                    operation="convert_to_datetime",
                    affected_columns=columns,
                    parameters={"date_format": date_format or "auto", "failed_conversions": failure_counts},
                )
                st.success(f"Applied step {entry['step_id']}: converted columns to datetime.")
                st.rerun()

    except ValueError as exc:
        st.error(str(exc))


def _render_categorical_tab(dataframe: pd.DataFrame) -> None:
    st.subheader("Categorical tools")
    categorical_columns = _categorical_columns(dataframe)
    if not categorical_columns:
        st.info("No categorical columns are currently available for categorical cleaning.")
        return

    cat_tabs = st.tabs(["Trim whitespace", "Case standardization", "Mapping UI", "Rare grouping", "One-hot encode"])

    with cat_tabs[0]:
        columns = st.multiselect("Columns to trim", categorical_columns, key="trim_columns")
        if columns:
            candidate_df = trim_whitespace(dataframe, columns)
            _render_before_after(
                _safe_preview(dataframe, columns),
                _safe_preview(candidate_df, columns),
                "Before trim",
                "After trim",
            )
            if st.button("Apply trim", key="apply_trim"):
                entry = apply_transformation(
                    candidate_df,
                    operation="trim_whitespace",
                    affected_columns=columns,
                    parameters={"columns": columns},
                )
                st.success(f"Applied step {entry['step_id']}: trimmed whitespace.")
                st.rerun()

    with cat_tabs[1]:
        columns = st.multiselect("Columns to standardize", categorical_columns, key="case_columns")
        case_style = st.selectbox("Case style", ["lower", "title", "upper"], key="case_style")
        if columns:
            candidate_df = standardize_case(dataframe, columns, case_style)
            _render_before_after(
                _safe_preview(dataframe, columns),
                _safe_preview(candidate_df, columns),
                "Before case standardization",
                "After case standardization",
            )
            if st.button("Apply case standardization", key="apply_case"):
                entry = apply_transformation(
                    candidate_df,
                    operation="standardize_case",
                    affected_columns=columns,
                    parameters={"case_style": case_style},
                )
                st.success(f"Applied step {entry['step_id']}: standardized case.")
                st.rerun()

    with cat_tabs[2]:
        column = st.selectbox("Column to map", categorical_columns, key="mapping_column")
        unique_values = dataframe[column].dropna().astype(str).sort_values().unique().tolist()
        mapping_template = pd.DataFrame({"original_value": unique_values, "replacement_value": unique_values})
        edited_mapping = st.data_editor(mapping_template, use_container_width=True, num_rows="fixed", key="category_mapping_editor")
        group_unmapped = st.checkbox("Group values not listed in the mapping to 'Other'", key="group_unmapped_other")

        mapping = {
            row["original_value"]: row["replacement_value"]
            for _, row in edited_mapping.iterrows()
            if str(row["replacement_value"]).strip() and row["replacement_value"] != row["original_value"]
        }
        candidate_df = map_categorical_values(dataframe, column, mapping, group_unmapped_to_other=group_unmapped)
        before_uniques = pd.DataFrame({"before": pd.Series(dataframe[column].astype(str).value_counts().head(20))})
        after_uniques = pd.DataFrame({"after": pd.Series(candidate_df[column].astype(str).value_counts().head(20))})
        _render_before_after(before_uniques, after_uniques, "Unique values before", "Unique values after")

        if st.button("Apply category mapping", key="apply_mapping"):
            entry = apply_transformation(
                candidate_df,
                operation="map_categories",
                affected_columns=[column],
                parameters={"mapping": mapping, "group_unmapped_to_other": group_unmapped},
            )
            st.success(f"Applied step {entry['step_id']}: updated categories in {column}.")
            st.rerun()

    with cat_tabs[3]:
        column = st.selectbox("Column for rare-category grouping", categorical_columns, key="rare_group_column")
        threshold_kind = st.radio("Threshold type", ["count", "percent"], horizontal=True, key="rare_threshold_kind")
        if threshold_kind == "count":
            threshold = float(st.number_input("Minimum count to keep a category", min_value=1, value=10, step=1, key="rare_count"))
        else:
            threshold = st.slider("Minimum share to keep a category", 0.0, 1.0, 0.02, 0.01, key="rare_percent")

        candidate_df, rare_values = group_rare_categories(dataframe, column, threshold, threshold_kind)
        st.write("Categories that would be grouped:", rare_values if rare_values else "None")
        _render_before_after(
            pd.DataFrame({"before": dataframe[column].astype(str).value_counts().head(20)}),
            pd.DataFrame({"after": candidate_df[column].astype(str).value_counts().head(20)}),
            "Unique values before",
            "Unique values after",
        )

        if st.button("Apply rare-category grouping", key="apply_rare_grouping"):
            entry = apply_transformation(
                candidate_df,
                operation="group_rare_categories",
                affected_columns=[column],
                parameters={"threshold_kind": threshold_kind, "threshold": threshold, "grouped_values": rare_values},
            )
            st.success(f"Applied step {entry['step_id']}: grouped rare categories into 'Other'.")
            st.rerun()

    with cat_tabs[4]:
        columns = st.multiselect("Columns to one-hot encode", categorical_columns, key="one_hot_columns")
        if columns:
            candidate_df = one_hot_encode_columns(dataframe, columns)
            st.write(f"New column count after encoding: {candidate_df.shape[1]}")
            if st.button("Apply one-hot encoding", key="apply_one_hot"):
                entry = apply_transformation(
                    candidate_df,
                    operation="one_hot_encode",
                    affected_columns=columns,
                    parameters={"columns": columns},
                )
                st.success(f"Applied step {entry['step_id']}: one-hot encoded selected columns.")
                st.rerun()


def _render_numeric_cleaning_tab(dataframe: pd.DataFrame) -> None:
    st.subheader("Numeric cleaning and outliers")
    numeric_columns = _numeric_columns(dataframe)
    if not numeric_columns:
        st.info("No numeric columns are available for outlier analysis yet.")
        return

    column = st.selectbox("Numeric column", numeric_columns, key="outlier_column")
    method = st.radio("Detection method", ["iqr", "zscore"], horizontal=True, key="outlier_method")
    iqr_multiplier = st.slider("IQR multiplier", 0.5, 3.5, 1.5, 0.1, key="iqr_multiplier") if method == "iqr" else 1.5
    z_threshold = st.slider("Z-score threshold", 1.0, 5.0, 3.0, 0.1, key="z_threshold") if method == "zscore" else 3.0

    try:
        summary = describe_outliers(
            dataframe=dataframe,
            column=column,
            method=method,
            iqr_multiplier=iqr_multiplier,
            z_threshold=z_threshold,
        )
        metric_columns = st.columns(3)
        metric_columns[0].metric("Outliers detected", summary["outlier_count"])
        metric_columns[1].metric("Lower bound", f"{summary['lower_bound']:.3f}")
        metric_columns[2].metric("Upper bound", f"{summary['upper_bound']:.3f}")

        st.dataframe(dataframe.loc[summary["outlier_mask"], [column]].head(50), use_container_width=True)
        action = st.radio("Action", ["Cap / winsorize", "Remove outlier rows", "Do nothing"], horizontal=True, key="outlier_action")

        if action == "Cap / winsorize":
            candidate_df, impacted_count = cap_outliers(
                dataframe,
                column=column,
                method=method,
                iqr_multiplier=iqr_multiplier,
                z_threshold=z_threshold,
            )
            _render_before_after(
                dataframe.loc[summary["outlier_mask"], [column]].head(10),
                candidate_df.loc[summary["outlier_mask"], [column]].head(10),
                "Before capping",
                "After capping",
            )
            if st.button("Apply outlier capping", key="apply_outlier_cap"):
                entry = apply_transformation(
                    candidate_df,
                    operation="cap_outliers",
                    affected_columns=[column],
                    parameters={"method": method, "iqr_multiplier": iqr_multiplier, "z_threshold": z_threshold, "impacted_count": impacted_count},
                )
                st.success(f"Applied step {entry['step_id']}: capped {impacted_count} outlier values.")
                st.rerun()

        elif action == "Remove outlier rows":
            candidate_df, impacted_count = remove_outlier_rows(
                dataframe,
                column=column,
                method=method,
                iqr_multiplier=iqr_multiplier,
                z_threshold=z_threshold,
            )
            st.write(f"Rows that would be removed: {impacted_count}")
            if st.button("Apply outlier row removal", key="apply_outlier_remove"):
                entry = apply_transformation(
                    candidate_df,
                    operation="remove_outlier_rows",
                    affected_columns=[column],
                    parameters={"method": method, "iqr_multiplier": iqr_multiplier, "z_threshold": z_threshold, "rows_removed": impacted_count},
                )
                st.success(f"Applied step {entry['step_id']}: removed {impacted_count} outlier rows.")
                st.rerun()

    except ValueError as exc:
        st.error(str(exc))


def _render_scaling_tab(dataframe: pd.DataFrame) -> None:
    st.subheader("Scaling")
    numeric_columns = _numeric_columns(dataframe)
    if not numeric_columns:
        st.info("No numeric columns are available for scaling.")
        return

    columns = st.multiselect("Numeric columns to scale", numeric_columns, key="scaling_columns")
    method = st.radio("Scaling method", ["minmax", "zscore"], horizontal=True, key="scaling_method")
    if not columns:
        return

    try:
        candidate_df, before_stats, after_stats = scale_numeric_columns(dataframe, columns, method)
        _render_before_after(before_stats, after_stats, "Before scaling stats", "After scaling stats")
        if st.button("Apply scaling", key="apply_scaling"):
            entry = apply_transformation(
                candidate_df,
                operation="scale_columns",
                affected_columns=columns,
                parameters={"method": method},
            )
            st.success(f"Applied step {entry['step_id']}: scaled selected numeric columns.")
            st.rerun()
    except ValueError as exc:
        st.error(str(exc))


def _render_column_ops_tab(dataframe: pd.DataFrame) -> None:
    st.subheader("Column operations")
    op_tabs = st.tabs(["Rename", "Drop", "Formula column", "Binning"])

    with op_tabs[0]:
        column = st.selectbox("Column to rename", dataframe.columns.tolist(), key="rename_column")
        new_name = st.text_input("New column name", key="new_column_name")
        if column and new_name:
            try:
                candidate_df = rename_dataframe_columns(dataframe, {column: new_name})
                if st.button("Apply rename", key="apply_rename"):
                    entry = apply_transformation(
                        candidate_df,
                        operation="rename_column",
                        affected_columns=[column],
                        parameters={"rename_map": {column: new_name}},
                    )
                    st.success(f"Applied step {entry['step_id']}: renamed {column} to {new_name}.")
                    st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    with op_tabs[1]:
        columns = st.multiselect("Columns to drop", dataframe.columns.tolist(), key="drop_columns")
        if columns:
            st.write(f"Columns that would be dropped: {', '.join(columns)}")
            candidate_df = drop_selected_columns(dataframe, columns)
            if st.button("Apply column drop", key="apply_drop_columns"):
                entry = apply_transformation(
                    candidate_df,
                    operation="drop_columns",
                    affected_columns=columns,
                    parameters={"columns": columns},
                )
                st.success(f"Applied step {entry['step_id']}: dropped {len(columns)} columns.")
                st.rerun()

    with op_tabs[2]:
        formula_choice = st.selectbox(
            "Formula type",
            {
                "colA / colB": "divide_columns",
                "colA - mean(colA)": "subtract_column_mean",
                "log(colA)": "log_column",
            },
            format_func=lambda label: label,
            key="formula_choice",
        )
        source_column = st.selectbox("Primary source column", dataframe.columns.tolist(), key="formula_source_column")
        other_column = None
        if formula_choice == "colA / colB":
            other_column = st.selectbox("Denominator column", dataframe.columns.tolist(), key="formula_other_column")
        new_column_name = st.text_input("New formula column name", key="formula_new_column")
        if source_column and new_column_name:
            try:
                candidate_df = create_formula_column(
                    dataframe,
                    new_column_name=new_column_name,
                    formula_type={"colA / colB": "divide_columns", "colA - mean(colA)": "subtract_column_mean", "log(colA)": "log_column"}[formula_choice],
                    source_column=source_column,
                    other_column=other_column,
                )
                _render_before_after(
                    _safe_preview(dataframe, [source_column] + ([other_column] if other_column else [])),
                    _safe_preview(candidate_df, [new_column_name]),
                    "Inputs",
                    "New column preview",
                )
                if st.button("Apply formula column", key="apply_formula"):
                    entry = apply_transformation(
                        candidate_df,
                        operation="create_formula_column",
                        affected_columns=[source_column] + ([other_column] if other_column else []),
                        parameters={"formula_type": formula_choice, "new_column_name": new_column_name},
                    )
                    st.success(f"Applied step {entry['step_id']}: created {new_column_name}.")
                    st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    with op_tabs[3]:
        numeric_columns = _numeric_columns(dataframe)
        if not numeric_columns:
            st.info("At least one numeric column is required for binning.")
        else:
            column = st.selectbox("Numeric column to bin", numeric_columns, key="bin_column")
            new_column_name = st.text_input("New binned column name", key="binned_column_name")
            method = st.radio("Binning method", ["equal_width", "quantile"], horizontal=True, key="bin_method")
            bins = int(st.number_input("Number of bins", min_value=2, max_value=20, value=4, step=1, key="bin_count"))
            if column and new_column_name:
                try:
                    candidate_df = bin_numeric_column(dataframe, column, new_column_name, bins, method)
                    st.dataframe(candidate_df[new_column_name].value_counts(dropna=False).rename_axis("bin").reset_index(name="count"))
                    if st.button("Apply binning", key="apply_binning"):
                        entry = apply_transformation(
                            candidate_df,
                            operation="bin_numeric_column",
                            affected_columns=[column],
                            parameters={"new_column_name": new_column_name, "method": method, "bins": bins},
                        )
                        st.success(f"Applied step {entry['step_id']}: created binned column {new_column_name}.")
                        st.rerun()
                except ValueError as exc:
                    st.error(str(exc))


def _render_validation_tab(dataframe: pd.DataFrame) -> None:
    st.subheader("Validation rules")
    rule_type = st.selectbox(
        "Rule type",
        {
            "Numeric range rule": "numeric_range",
            "Allowed categories rule": "allowed_categories",
            "Non-null rule": "non_null",
        },
        format_func=lambda label: label,
        key="validation_rule_type",
    )
    rule_name = st.text_input("Rule name", value="validation_rule", key="validation_rule_name")

    preview_result = None
    try:
        if rule_type == "Numeric range rule":
            numeric_columns = _numeric_columns(dataframe)
            if not numeric_columns:
                st.info("Numeric columns are required for range validation.")
            else:
                column = st.selectbox("Numeric column", numeric_columns, key="validation_numeric_column")
                minimum = _parse_optional_float(st.text_input("Minimum value", key="validation_minimum"), "Minimum value")
                maximum = _parse_optional_float(st.text_input("Maximum value", key="validation_maximum"), "Maximum value")
                if minimum is not None or maximum is not None:
                    preview_result = run_validation_rule(
                        dataframe,
                        rule_type="numeric_range",
                        column=column,
                        minimum=minimum,
                        maximum=maximum,
                        rule_name=rule_name or "numeric_range_rule",
                    )
                else:
                    st.caption("Enter a minimum or maximum value to preview this rule.")
        elif rule_type == "Allowed categories rule":
            categorical_columns = _categorical_columns(dataframe)
            if not categorical_columns:
                st.info("Categorical columns are required for allowed-category validation.")
            else:
                column = st.selectbox("Categorical column", categorical_columns, key="validation_allowed_column")
                allowed_values = st.multiselect(
                    "Allowed values",
                    sorted(dataframe[column].dropna().astype(str).unique().tolist()),
                    key="validation_allowed_values",
                )
                if allowed_values:
                    preview_result = run_validation_rule(
                        dataframe,
                        rule_type="allowed_categories",
                        column=column,
                        allowed_values=allowed_values,
                        rule_name=rule_name or "allowed_categories_rule",
                    )
                else:
                    st.caption("Choose one or more allowed values to preview this rule.")
        else:
            column = st.selectbox("Column", dataframe.columns.tolist(), key="validation_non_null_column")
            preview_result = run_validation_rule(
                dataframe,
                rule_type="non_null",
                column=column,
                rule_name=rule_name or "non_null_rule",
            )

        if preview_result is not None:
            st.metric("Violations found", preview_result["violation_count"])
            st.dataframe(preview_result["violations"].head(50), use_container_width=True)
            if st.button("Run rule and store result", key="apply_validation_rule"):
                st.session_state["validation_results"].append(preview_result)
                st.success(f"Stored validation result for rule: {preview_result['rule_name']}")
                st.rerun()
    except ValueError as exc:
        st.error(str(exc))

    if st.session_state["validation_results"]:
        st.divider()
        st.caption("Stored validation results")
        st.dataframe(validation_results_summary(st.session_state["validation_results"]), use_container_width=True)
        violations_df = combine_validation_violations(st.session_state["validation_results"])
        if not violations_df.empty:
            st.dataframe(violations_df.head(100), use_container_width=True, height=260)
            st.download_button(
                "Export violations as CSV",
                data=validation_violations_to_csv_bytes(st.session_state["validation_results"]),
                file_name="validation_violations.csv",
                mime="text/csv",
            )


def _render_cleaning_page() -> None:
    st.header("Cleaning & Preparation Studio")
    st.write("Every transformation here updates the working dataframe, logs the action, and becomes available for export later.")

    if not has_data():
        st.info("Load a dataset on the Upload & Overview page first.")
        return

    dataframe = st.session_state["working_df"]
    st.caption(f"Current working shape: {dataframe.shape[0]} rows x {dataframe.shape[1]} columns")
    st.dataframe(dataframe.head(10), use_container_width=True)

    tabs = st.tabs(
        [
            "Missing values",
            "Duplicates",
            "Data types",
            "Categorical tools",
            "Numeric cleaning",
            "Scaling",
            "Column operations",
            "Validation",
        ]
    )
    with tabs[0]:
        _render_missing_values_tab(dataframe)
    with tabs[1]:
        _render_duplicates_tab(dataframe)
    with tabs[2]:
        _render_dtype_tab(dataframe)
    with tabs[3]:
        _render_categorical_tab(dataframe)
    with tabs[4]:
        _render_numeric_cleaning_tab(dataframe)
    with tabs[5]:
        _render_scaling_tab(dataframe)
    with tabs[6]:
        _render_column_ops_tab(dataframe)
    with tabs[7]:
        _render_validation_tab(dataframe)

    st.divider()
    st.subheader("Transformation log")
    st.dataframe(_log_table(st.session_state["transform_log"]), use_container_width=True, height=280)


def _render_visualization_page() -> None:
    st.header("Visualization Builder")
    st.write("Charts are created from the transformed working dataset after applying the selected filters.")

    if not has_data():
        st.info("Load and prepare a dataset before building visualizations.")
        return

    dataframe = st.session_state["working_df"]
    numeric_columns = _numeric_columns(dataframe)
    categorical_columns = _categorical_columns(dataframe)

    control_column, chart_column = st.columns([1, 1.6])

    with control_column:
        chart_type = st.selectbox(
            "Plot type",
            ["Histogram", "Box Plot", "Scatter Plot", "Line Chart", "Bar Chart", "Correlation Heatmap"],
            key="chart_type",
        )
        x_column = st.selectbox("X column", ["None"] + dataframe.columns.tolist(), key="chart_x_column")
        y_column = st.selectbox("Y column", ["None"] + dataframe.columns.tolist(), key="chart_y_column")
        color_column = st.selectbox("Optional color/group column", ["None"] + dataframe.columns.tolist(), key="chart_color_column")
        aggregation = st.selectbox("Optional aggregation", ["sum", "mean", "count", "median"], key="chart_aggregation")

        category_filter_column = st.selectbox(
            "Category filter column",
            ["None"] + categorical_columns,
            key="category_filter_column",
        )
        category_filter_values = []
        if category_filter_column != "None":
            category_filter_values = st.multiselect(
                "Category filter values",
                sorted(dataframe[category_filter_column].dropna().astype(str).unique().tolist()),
                key="category_filter_values",
            )

        numeric_filter_column = st.selectbox(
            "Numeric range filter column",
            ["None"] + numeric_columns,
            key="numeric_filter_column",
        )
        numeric_range = None
        if numeric_filter_column != "None":
            numeric_series = pd.to_numeric(dataframe[numeric_filter_column], errors="coerce").dropna()
            if not numeric_series.empty:
                numeric_range = st.slider(
                    "Numeric range",
                    float(numeric_series.min()),
                    float(numeric_series.max()),
                    (float(numeric_series.min()), float(numeric_series.max())),
                    key="numeric_range_slider",
                )

        top_n = None
        if chart_type == "Bar Chart":
            top_n = int(st.number_input("Top N categories", min_value=1, max_value=50, value=10, step=1))

        filtered_df = filter_dataframe(
            dataframe,
            category_column=None if category_filter_column == "None" else category_filter_column,
            category_values=category_filter_values,
            numeric_column=None if numeric_filter_column == "None" else numeric_filter_column,
            numeric_range=numeric_range,
        )

        st.metric("Rows after filters", int(filtered_df.shape[0]))
        if filtered_df.empty:
            st.warning("The current filters produced no rows.")
            return

    with chart_column:
        try:
            figure = build_chart(
                filtered_df,
                chart_type=chart_type,
                x_column=None if x_column == "None" else x_column,
                y_column=None if y_column == "None" else y_column,
                color_column=None if color_column == "None" else color_column,
                aggregation=aggregation,
                top_n=top_n,
            )
            st.pyplot(figure, clear_figure=True, use_container_width=True)
            st.dataframe(filtered_df.head(25), use_container_width=True)
        except ValueError as exc:
            st.info(str(exc))


def _render_export_page() -> None:
    st.header("Export & Report")
    st.write("Download the cleaned dataset, the transformation report, the JSON recipe, and any validation violations.")

    if not has_data():
        st.info("Load a dataset before exporting outputs.")
        return

    original_df = st.session_state["original_df"]
    working_df = st.session_state["working_df"]
    transform_log = st.session_state["transform_log"]
    validation_results = st.session_state["validation_results"]
    file_name = st.session_state.get("current_file_name")

    report = build_transformation_report(
        file_name=file_name,
        original_df=original_df,
        working_df=working_df,
        transform_log=transform_log,
        validation_results=validation_results,
    )

    metric_columns = st.columns(4)
    metric_columns[0].metric("Original rows", int(original_df.shape[0]))
    metric_columns[1].metric("Current rows", int(working_df.shape[0]))
    metric_columns[2].metric("Logged steps", len(transform_log))
    metric_columns[3].metric("Validation rules stored", len(validation_results))

    st.subheader("Transformation log")
    st.dataframe(_log_table(transform_log), use_container_width=True, height=260)

    button_columns = st.columns(3)
    with button_columns[0]:
        st.download_button(
            "Download cleaned CSV",
            data=dataframe_to_csv_bytes(working_df),
            file_name="godata_cleaned_dataset.csv",
            mime="text/csv",
        )
        st.download_button(
            "Download cleaned Excel",
            data=dataframe_to_excel_bytes(working_df),
            file_name="godata_cleaned_dataset.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    with button_columns[1]:
        st.download_button(
            "Download transformation report",
            data=transformation_report_to_json_bytes(report),
            file_name="godata_transformation_report.json",
            mime="application/json",
        )
        st.download_button(
            "Download JSON recipe",
            data=recipe_to_json_bytes(transform_log),
            file_name="godata_recipe.json",
            mime="application/json",
        )
    with button_columns[2]:
        st.download_button(
            "Download replay snippet",
            data=pipeline_snippet_to_bytes(transform_log),
            file_name="godata_recipe_replay.py",
            mime="text/x-python",
        )
        violations_bytes = validation_violations_to_csv_bytes(validation_results)
        st.download_button(
            "Download validation violations",
            data=violations_bytes,
            file_name="godata_validation_violations.csv",
            mime="text/csv",
            disabled=not bool(violations_bytes),
        )

    preview_tabs = st.tabs(["Transformation report preview", "Recipe preview", "Validation violations"])
    with preview_tabs[0]:
        st.json(report)
    with preview_tabs[1]:
        st.code(recipe_to_json_bytes(transform_log).decode("utf-8"), language="json")
    with preview_tabs[2]:
        violations_df = combine_validation_violations(validation_results)
        if violations_df.empty:
            st.info("No validation violations are stored.")
        else:
            st.dataframe(violations_df, use_container_width=True, height=320)


def main() -> None:
    page = _show_state_actions()
    if page == "Upload & Overview":
        _render_upload_page()
    elif page == "Cleaning & Preparation Studio":
        _render_cleaning_page()
    elif page == "Visualization Builder":
        _render_visualization_page()
    else:
        _render_export_page()


if __name__ == "__main__":
    main()
