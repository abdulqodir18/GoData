from __future__ import annotations

import math

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st


def filter_dataframe(
    dataframe: pd.DataFrame,
    category_column: str | None = None,
    category_values: list[object] | None = None,
    numeric_column: str | None = None,
    numeric_range: tuple[float, float] | None = None,
) -> pd.DataFrame:
    filtered = dataframe.copy()

    if category_column and category_values:
        filtered = filtered[filtered[category_column].astype(str).isin([str(value) for value in category_values])]

    if numeric_column and numeric_range is not None:
        numeric_series = pd.to_numeric(filtered[numeric_column], errors="coerce")
        lower, upper = numeric_range
        filtered = filtered[(numeric_series >= lower) & (numeric_series <= upper)]

    return filtered


@st.cache_data(show_spinner=False)
def correlation_matrix(dataframe: pd.DataFrame) -> pd.DataFrame:
    numeric_dataframe = dataframe.select_dtypes(include=np.number)
    return numeric_dataframe.corr(numeric_only=True)


def _set_axis_title(axis, title: str) -> None:
    axis.set_title(title)
    axis.grid(alpha=0.2)


def _category_palette(size: int) -> list:
    cmap = plt.cm.get_cmap("tab20", max(size, 1))
    return [cmap(index) for index in range(size)]


def _build_bar_data(
    dataframe: pd.DataFrame,
    x_column: str,
    y_column: str | None,
    color_column: str | None,
    aggregation: str,
    top_n: int | None,
) -> pd.DataFrame:
    group_columns = [x_column] + ([color_column] if color_column else [])

    if aggregation == "count" or not y_column:
        bar_data = dataframe.groupby(group_columns, dropna=False).size().reset_index(name="value")
    else:
        bar_data = (
            dataframe.groupby(group_columns, dropna=False)[y_column]
            .agg(aggregation)
            .reset_index(name="value")
        )

    if top_n:
        totals = bar_data.groupby(x_column)["value"].sum().sort_values(ascending=False).head(top_n)
        bar_data = bar_data[bar_data[x_column].isin(totals.index)]
    return bar_data


def build_chart(
    dataframe: pd.DataFrame,
    chart_type: str,
    x_column: str | None = None,
    y_column: str | None = None,
    color_column: str | None = None,
    aggregation: str = "sum",
    top_n: int | None = None,
) -> plt.Figure:
    figure, axis = plt.subplots(figsize=(10, 5.5))

    if chart_type == "Histogram":
        if x_column is None:
            raise ValueError("Choose a numeric column for the histogram.")
        series = pd.to_numeric(dataframe[x_column], errors="coerce").dropna()
        if series.empty:
            raise ValueError("The selected histogram column has no numeric values.")
        axis.hist(series, bins=min(30, max(10, int(math.sqrt(len(series))))), color="#1f77b4", edgecolor="white")
        axis.set_xlabel(x_column)
        axis.set_ylabel("Count")
        _set_axis_title(axis, f"Distribution of {x_column}")

    elif chart_type == "Box Plot":
        if y_column is None and x_column is None:
            raise ValueError("Choose at least one numeric column for the box plot.")
        numeric_column = y_column or x_column
        numeric_series = pd.to_numeric(dataframe[numeric_column], errors="coerce")
        if color_column:
            groups = []
            labels = []
            for label, group in dataframe.groupby(color_column, dropna=False):
                candidate = pd.to_numeric(group[numeric_column], errors="coerce").dropna()
                if not candidate.empty:
                    labels.append(str(label))
                    groups.append(candidate)
            if not groups:
                raise ValueError("Not enough grouped numeric data to render the box plot.")
            axis.boxplot(groups, labels=labels, patch_artist=True)
            axis.tick_params(axis="x", rotation=45)
            axis.set_xlabel(color_column)
        else:
            axis.boxplot(numeric_series.dropna())
        axis.set_ylabel(numeric_column)
        _set_axis_title(axis, f"Box plot of {numeric_column}")

    elif chart_type == "Scatter Plot":
        if x_column is None or y_column is None:
            raise ValueError("Choose both X and Y columns for the scatter plot.")
        x_series = pd.to_numeric(dataframe[x_column], errors="coerce")
        y_series = pd.to_numeric(dataframe[y_column], errors="coerce")
        plot_dataframe = pd.DataFrame({x_column: x_series, y_column: y_series}).dropna()
        if color_column:
            plot_dataframe[color_column] = dataframe.loc[plot_dataframe.index, color_column]
            palette = _category_palette(plot_dataframe[color_column].nunique(dropna=False))
            for color, (label, group) in zip(palette, plot_dataframe.groupby(color_column, dropna=False)):
                axis.scatter(group[x_column], group[y_column], alpha=0.7, label=str(label), color=color)
            axis.legend(title=color_column, bbox_to_anchor=(1.02, 1), loc="upper left")
        else:
            axis.scatter(plot_dataframe[x_column], plot_dataframe[y_column], alpha=0.7, color="#2ca02c")
        axis.set_xlabel(x_column)
        axis.set_ylabel(y_column)
        _set_axis_title(axis, f"{y_column} vs {x_column}")

    elif chart_type == "Line Chart":
        if x_column is None or y_column is None:
            raise ValueError("Choose both X and Y columns for the line chart.")
        plot_dataframe = dataframe[[x_column, y_column] + ([color_column] if color_column else [])].copy()
        plot_dataframe[y_column] = pd.to_numeric(plot_dataframe[y_column], errors="coerce")
        plot_dataframe[x_column] = pd.to_datetime(plot_dataframe[x_column], errors="ignore")
        plot_dataframe = plot_dataframe.dropna(subset=[y_column]).sort_values(x_column)
        if color_column:
            palette = _category_palette(plot_dataframe[color_column].nunique(dropna=False))
            for color, (label, group) in zip(palette, plot_dataframe.groupby(color_column, dropna=False)):
                axis.plot(group[x_column], group[y_column], label=str(label), linewidth=2, color=color)
            axis.legend(title=color_column, bbox_to_anchor=(1.02, 1), loc="upper left")
        else:
            axis.plot(plot_dataframe[x_column], plot_dataframe[y_column], linewidth=2, color="#ff7f0e")
        axis.set_xlabel(x_column)
        axis.set_ylabel(y_column)
        _set_axis_title(axis, f"{y_column} over {x_column}")

    elif chart_type == "Bar Chart":
        if x_column is None:
            raise ValueError("Choose an X column for the bar chart.")
        bar_data = _build_bar_data(
            dataframe=dataframe,
            x_column=x_column,
            y_column=y_column,
            color_column=color_column,
            aggregation=aggregation,
            top_n=top_n,
        )
        if bar_data.empty:
            raise ValueError("The selected filters produced no rows for the bar chart.")
        if color_column:
            pivoted = bar_data.pivot(index=x_column, columns=color_column, values="value").fillna(0)
            pivoted.plot(kind="bar", ax=axis)
            axis.legend(title=color_column, bbox_to_anchor=(1.02, 1), loc="upper left")
        else:
            axis.bar(bar_data[x_column].astype(str), bar_data["value"], color="#9467bd")
        axis.tick_params(axis="x", rotation=45)
        axis.set_xlabel(x_column)
        axis.set_ylabel(f"{aggregation.title()} value" if aggregation != "count" else "Count")
        _set_axis_title(axis, f"Bar chart by {x_column}")

    elif chart_type == "Correlation Heatmap":
        corr = correlation_matrix(dataframe)
        if corr.empty or corr.shape[1] < 2:
            raise ValueError("At least two numeric columns are needed for a correlation heatmap.")
        image = axis.imshow(corr, cmap="coolwarm", vmin=-1, vmax=1)
        axis.set_xticks(range(len(corr.columns)))
        axis.set_yticks(range(len(corr.index)))
        axis.set_xticklabels(corr.columns, rotation=45, ha="right")
        axis.set_yticklabels(corr.index)
        for row_index in range(corr.shape[0]):
            for column_index in range(corr.shape[1]):
                axis.text(column_index, row_index, f"{corr.iloc[row_index, column_index]:.2f}", ha="center", va="center")
        figure.colorbar(image, ax=axis, fraction=0.046, pad=0.04)
        _set_axis_title(axis, "Correlation heatmap")

    else:
        raise ValueError("Unsupported chart type.")

    figure.tight_layout()
    return figure
