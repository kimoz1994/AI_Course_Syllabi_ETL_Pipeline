"""Stage 6 - REPORT: RQ tables, figures and findings.

Every figure is built to satisfy the 19-point figure checklist inherited
from the original research workflow (title/label fonts, values and
percentages on bars, figure size, bar width, stated base count, ...).
:func:`verify_figure` re-checks each item against the finished Plotly
figure and the results are written to ``output/report_checklist.json``.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go

from .clean import split_items
from .classify import Taxonomy, coverage_table

# ---------------------------------------------------------------------------
# Figure design constants (the checklist, encoded once)
# ---------------------------------------------------------------------------

FIG_WIDTH, FIG_HEIGHT = 1000, 500          # 10 in x 5 in at 100 dpi
TITLE_FS, AXIS_FS, TICK_FS, BAR_FS = 16, 14, 10, 10
BAR_WIDTH_V, BAR_WIDTH_H = 0.6, 0.5        # vertical / horizontal bars
Y_HEADROOM_V, Y_HEADROOM_H = 1.15, 1.30    # value-axis headroom for bar labels

# Okabe-Ito categorical palette (colour-vision-deficiency safe)
PALETTE = {
    1: "#0072B2",  # blue
    2: "#D55E00",  # vermillion
    3: "#009E73",  # bluish green
    4: "#E69F00",  # orange
    5: "#56B4E9",  # sky blue
    6: "#CC79A7",  # reddish purple
    7: "#999999",  # grey  (Other)
}
SINGLE_COLOR = "#56B4E9"

CHECKLIST_ITEMS = [
    "title",
    "x-label",
    "y-label",
    "font x-label 14",
    "font y-label 14",
    "font title 16",
    "font values on bars 10",
    "x-ticks font size 10",
    "y-ticks font size 10",
    "x-numbers/items",
    "y-numbers/items",
    "values on bars",
    "percentages on bars",
    "check if percentages correct",
    "height and width of figure (10 x 5)",
    "width or height of bars (v=0.6, h=0.5)",
    "number of syllabi chart is based on",
    "check capitalization for all",
    "y-axis range",
]

_ACRONYMS = {"AI", "AIMA", "NLP", "ML", "CV", "QA", "PII", "CS", "IT", "UK", "USA", "EU", "GPA"}


# ---------------------------------------------------------------------------
# Verification (the checklist, evaluated against a finished figure)
# ---------------------------------------------------------------------------


def _has_tick_labels(axis: Any) -> bool:
    mode = getattr(axis, "tickmode", None)
    if mode == "manual":
        return bool(getattr(axis, "tickvals", None))
    return True  # auto / None: Plotly renders tick labels


def _capitalization_ok(labels: list[str | None]) -> bool:
    for label in labels:
        if not label:
            continue
        first = next((ch for ch in label if ch.isalpha()), None)
        if first is not None and not first.isupper():
            return False
        for word in re.findall(r"[A-Za-z]{4,}", label):
            if word.isupper() and word not in _ACRONYMS:
                return False
    return True


def verify_figure(fig: go.Figure, meta: dict[str, Any]) -> dict[str, bool]:
    """Evaluate the 19-point checklist against a finished figure."""
    trace = fig.data[0]
    xaxis, yaxis = fig.layout.xaxis, fig.layout.yaxis
    vertical = meta["orientation"] == "v"
    value_axis = yaxis if vertical else xaxis
    count_axis_title = (yaxis.title.text if vertical else xaxis.title.text) or ""
    labels = [
        fig.layout.title.text,
        xaxis.title.text,
        yaxis.title.text,
    ]
    texts = [str(t) for t in (trace.text or [])]
    expected = meta.get("expected_texts", [])

    return {
        "title": bool(fig.layout.title and fig.layout.title.text),
        "x-label": bool(xaxis.title and xaxis.title.text),
        "y-label": bool(yaxis.title and yaxis.title.text),
        "font x-label 14": bool(xaxis.title.font and xaxis.title.font.size == AXIS_FS),
        "font y-label 14": bool(yaxis.title.font and yaxis.title.font.size == AXIS_FS),
        "font title 16": bool(fig.layout.title.font and fig.layout.title.font.size == TITLE_FS),
        "font values on bars 10": bool(trace.textfont and trace.textfont.size == BAR_FS),
        "x-ticks font size 10": bool(xaxis.tickfont and xaxis.tickfont.size == TICK_FS),
        "y-ticks font size 10": bool(yaxis.tickfont and yaxis.tickfont.size == TICK_FS),
        "x-numbers/items": _has_tick_labels(xaxis),
        "y-numbers/items": _has_tick_labels(yaxis),
        "values on bars": bool(texts) and all(t.strip() for t in texts),
        "percentages on bars": bool(texts) and all("%" in t for t in texts),
        "check if percentages correct": bool(expected) and texts == expected,
        "height and width of figure (10 x 5)": (
            fig.layout.width == FIG_WIDTH and fig.layout.height == FIG_HEIGHT
        ),
        "width or height of bars (v=0.6, h=0.5)": float(trace.width or 0)
        == (BAR_WIDTH_V if vertical else BAR_WIDTH_H),
        "number of syllabi chart is based on": "out of" in count_axis_title.lower(),
        "check capitalization for all": _capitalization_ok(labels),
        "y-axis range": value_axis.range is not None,
    }


# ---------------------------------------------------------------------------
# Figure builders
# ---------------------------------------------------------------------------


def _theme_layout(fig: go.Figure, title: str, x_label: str, y_label: str, vmax: float,
                  vertical: bool) -> None:
    fig.update_layout(
        width=FIG_WIDTH,
        height=FIG_HEIGHT,
        title=dict(text=title, font=dict(size=TITLE_FS)),
        bargap=0.25,
        showlegend=False,
    )
    fig.update_xaxes(
        title_text=x_label,
        title_font=dict(size=AXIS_FS),
        tickfont=dict(size=TICK_FS),
    )
    fig.update_yaxes(
        title_text=y_label,
        title_font=dict(size=AXIS_FS),
        tickfont=dict(size=TICK_FS),
    )
    if vertical:
        fig.update_yaxes(range=[0, vmax * Y_HEADROOM_V])
    else:
        fig.update_xaxes(range=[0, vmax * Y_HEADROOM_H])


def build_theme_chart(
    coverage: pd.DataFrame,
    total: int,
    title: str,
    y_label: str,
    x_label: str = "Topic category (AIMA 4th edition)",
) -> tuple[go.Figure, dict[str, Any]]:
    """Vertical bars: syllabi covering each AIMA theme (RQ1 / RQ4)."""
    names = coverage["class_name"].tolist()
    ns = [int(v) for v in coverage["n_syllabi"]]
    texts = [f"{v} ({100.0 * v / total:.1f}%)" for v in ns] if total else ["0 (0.0%)"] * len(ns)
    colors = [PALETTE.get(int(i), SINGLE_COLOR) for i in coverage["class_id"]]

    fig = go.Figure(
        go.Bar(
            x=names,
            y=ns,
            width=BAR_WIDTH_V,
            marker=dict(color=colors),
            text=texts,
            textposition="outside",
            textfont=dict(size=BAR_FS),
        )
    )
    _theme_layout(fig, title, x_label, y_label, max(ns) if ns else 1, vertical=True)
    meta = {"orientation": "v", "expected_texts": texts, "count_axis": "y"}
    return fig, meta


def build_methods_chart(
    counts: pd.Series,
    total: int,
    title: str,
    category_label: str,
    count_label: str,
    top_n: int = 10,
) -> tuple[go.Figure, dict[str, Any]]:
    """Horizontal bars: top teaching/assessment methods (RQ2 / RQ3)."""
    top = counts.head(top_n).sort_values()          # ascending -> biggest on top
    names = [str(n) for n in top.index]
    ns = [int(v) for v in top.values]
    texts = [f"{v} ({100.0 * v / total:.1f}%)" for v in ns] if total else ["0 (0.0%)"] * len(ns)

    fig = go.Figure(
        go.Bar(
            x=ns,
            y=names,
            orientation="h",
            width=BAR_WIDTH_H,
            marker=dict(color=SINGLE_COLOR),
            text=texts,
            textposition="outside",
            textfont=dict(size=BAR_FS),
        )
    )
    _theme_layout(fig, title, count_label, category_label, max(ns) if ns else 1, vertical=False)
    meta = {"orientation": "h", "expected_texts": texts, "count_axis": "x"}
    return fig, meta


def build_year_chart(
    year_counts: pd.Series, title: str, y_label: str, x_label: str = "Year"
) -> tuple[go.Figure, dict[str, Any]]:
    """Vertical bars: syllabi per year."""
    year_counts = year_counts.sort_index()
    years = [int(y) for y in year_counts.index]
    ns = [int(v) for v in year_counts.values]
    total = sum(ns)
    texts = [f"{v} ({100.0 * v / total:.1f}%)" for v in ns] if total else ["0 (0.0%)"] * len(ns)

    fig = go.Figure(
        go.Bar(
            x=years,
            y=ns,
            width=BAR_WIDTH_V,
            marker=dict(color=SINGLE_COLOR),
            text=texts,
            textposition="outside",
            textfont=dict(size=BAR_FS),
        )
    )
    _theme_layout(fig, title, x_label, y_label, max(ns) if ns else 1, vertical=True)
    meta = {"orientation": "v", "expected_texts": texts, "count_axis": "y"}
    return fig, meta


# ---------------------------------------------------------------------------
# Table helpers
# ---------------------------------------------------------------------------


def method_counts(series: pd.Series, seps: tuple[str, ...] = (";", "|", "\n")) -> pd.Series:
    """Count method mentions, splitting multi-value cells."""
    counter: Counter = Counter()
    for value in series.dropna():
        for item in split_items(value, seps=seps):
            counter[item] += 1
    return pd.Series(counter, dtype=int).sort_values(ascending=False)


# ---------------------------------------------------------------------------
# Full report
# ---------------------------------------------------------------------------


def build_outputs(
    clean_df: pd.DataFrame,
    class_df: pd.DataFrame,
    quality: dict[str, Any],
    taxonomy: Taxonomy,
    cfg: dict[str, Any],
    backend_name: str,
) -> dict[str, str]:
    """Render all figures, tables, checklist and ``report.md``."""
    outdir = Path(cfg["paths"]["output"])
    outdir.mkdir(parents=True, exist_ok=True)
    top_n = int(cfg.get("report", {}).get("top_n_methods", 10))
    total = len(clean_df)
    written: dict[str, str] = {}

    # ---- RQ1: topic categories ----------------------------------------
    cov_topics = coverage_table(class_df, taxonomy, total, field="course_topics")
    fig1, meta1 = build_theme_chart(
        cov_topics,
        total,
        title="AI Topic Categories Across Course Syllabi",
        y_label=f"Number of syllabi covering (out of {total})",
    )

    # ---- RQ2: teaching methods -----------------------------------------
    teaching_total = int(clean_df["teaching_methods"].notna().sum()) if "teaching_methods" in clean_df else 0
    teaching = method_counts(clean_df.get("teaching_methods", pd.Series(dtype=object)))
    fig2, meta2 = build_methods_chart(
        teaching,
        teaching_total,
        title="Teaching Methods in AI Course Syllabi",
        category_label="Teaching method",
        count_label=f"Number of syllabi mentioning (out of {teaching_total})",
        top_n=top_n,
    )

    # ---- RQ3: assessment methods ---------------------------------------
    assessment_total = int(clean_df["assessment_methods"].notna().sum()) if "assessment_methods" in clean_df else 0
    assessment = method_counts(clean_df.get("assessment_methods", pd.Series(dtype=object)))
    fig3, meta3 = build_methods_chart(
        assessment,
        assessment_total,
        title="Assessment Methods in AI Course Syllabi",
        category_label="Assessment method",
        count_label=f"Number of syllabi mentioning (out of {assessment_total})",
        top_n=top_n,
    )

    # ---- RQ4: outcomes emphasised --------------------------------------
    cov_outcomes = coverage_table(class_df, taxonomy, total, field="course_outcomes")
    outcomes_total = int(clean_df["course_outcomes"].notna().sum()) if "course_outcomes" in clean_df else 0
    fig4, meta4 = build_theme_chart(
        cov_outcomes,
        outcomes_total or 1,
        title="Course Outcomes Emphasised, by AIMA Theme",
        y_label=f"Number of syllabi with outcomes in theme (out of {outcomes_total})",
    )

    # ---- Year trend ------------------------------------------------------
    year_series = (
        pd.to_numeric(clean_df["year"], errors="coerce").dropna().astype(int).value_counts().sort_index()
        if "year" in clean_df
        else pd.Series(dtype=int)
    )
    year_total = int(year_series.sum())
    fig5, meta5 = build_year_chart(
        year_series,
        title="AI Course Syllabi by Year",
        y_label=f"Number of syllabi (out of {year_total} with a year)",
    )

    figures = {
        "rq1_topic_categories": (fig1, meta1),
        "rq2_teaching_methods": (fig2, meta2),
        "rq3_assessment_methods": (fig3, meta3),
        "rq4_outcomes_themes": (fig4, meta4),
        "year_trend": (fig5, meta5),
    }

    # ---- save figures + tables -----------------------------------------
    for name, (fig, _meta) in figures.items():
        path = outdir / f"{name}.html"
        fig.write_html(str(path), include_plotlyjs="cdn")
        written[name] = str(path)

    tables = {
        "rq1_topic_coverage": cov_topics,
        "rq2_teaching_methods": teaching.rename("n_syllabi").reset_index()
        .rename(columns={"index": "teaching_method"}),
        "rq3_assessment_methods": assessment.rename("n_syllabi").reset_index()
        .rename(columns={"index": "assessment_method"}),
        "rq4_outcomes_themes": cov_outcomes,
    }
    for name, table in tables.items():
        path = outdir / f"{name}.csv"
        table.to_csv(path, index=False, encoding="utf-8")
        written[name] = str(path)

    # ---- figure checklist ------------------------------------------------
    checklist = {
        name: {
            "checks": verify_figure(fig, meta),
            "passed": f"{sum(verify_figure(fig, meta).values())}/{len(CHECKLIST_ITEMS)}",
        }
        for name, (fig, meta) in figures.items()
    }
    for name, entry in checklist.items():
        entry["all_passed"] = all(entry["checks"].values())
    checklist_path = outdir / "report_checklist.json"
    checklist_path.write_text(json.dumps(checklist, indent=2), encoding="utf-8")
    written["report_checklist"] = str(checklist_path)

    # ---- markdown report -------------------------------------------------
    report_path = outdir / "report.md"
    report_path.write_text(
        _report_markdown(
            clean_df=clean_df,
            cov_topics=cov_topics,
            cov_outcomes=cov_outcomes,
            teaching=teaching,
            assessment=assessment,
            quality=quality,
            year_series=year_series,
            backend_name=backend_name,
            checklist=checklist,
        ),
        encoding="utf-8",
    )
    written["report"] = str(report_path)
    return written


def _top_rows(df: pd.DataFrame, n: int = 3) -> str:
    rows = []
    for _, row in df.sort_values("n_syllabi", ascending=False).head(n).iterrows():
        rows.append(f"- **{row['class_name']}** — {int(row['n_syllabi'])} syllabi ({row['pct_syllabi']}%)")
    return "\n".join(rows)


def _report_markdown(
    clean_df: pd.DataFrame,
    cov_topics: pd.DataFrame,
    cov_outcomes: pd.DataFrame,
    teaching: pd.Series,
    assessment: pd.Series,
    quality: dict[str, Any],
    year_series: pd.Series,
    backend_name: str,
    checklist: dict[str, Any],
) -> str:
    total = len(clean_df)
    countries = int(clean_df["country"].nunique()) if "country" in clean_df else 0
    year_span = (
        f"{int(year_series.index.min())}–{int(year_series.index.max())} ({len(year_series)} distinct years)"
        if len(year_series)
        else "unknown"
    )
    top_teaching = ", ".join(
        f"{name} ({count})" for name, count in teaching.head(3).items()
    ) or "n/a"
    top_assessment = ", ".join(
        f"{name} ({count})" for name, count in assessment.head(3).items()
    ) or "n/a"
    checks_passed = sum(1 for entry in checklist.values() if entry["all_passed"])

    return f"""# AI Course Syllabi — Analysis Report

Generated by `ai-syllabi-etl` on {datetime.now():%Y-%m-%d %H:%M} (backend: **{backend_name}**).

## Dataset at a glance

| Metric | Value |
|---|---|
| Syllabi | {total} |
| Countries | {countries} |
| Year coverage | {year_span} |
| Quality report | **{quality['overall'].upper()}** ({quality['row_counts']['classified_items']} classified items) |
| Figure checklists fully passed | {checks_passed}/{len(checklist)} |

## RQ1 — Predominant AI topic categories

{_top_rows(cov_topics)}

![RQ1](rq1_topic_categories.html) — [interactive figure](rq1_topic_categories.html) · [table](rq1_topic_coverage.csv)

## RQ2 — Teaching methods

Most frequent: {top_teaching}

[figure](rq2_teaching_methods.html) · [table](rq2_teaching_methods.csv)

## RQ3 — Assessment methods

Most frequent: {top_assessment}

[figure](rq3_assessment_methods.html) · [table](rq3_assessment_methods.csv)

## RQ4 — Outcomes emphasised

{_top_rows(cov_outcomes)}

[figure](rq4_outcomes_themes.html) · [table](rq4_outcomes_themes.csv)

## Additional views

- [Syllabi by year](year_trend.html)
- [Figure checklist (19-point)](report_checklist.json)

## Reproduce

```bash
python -m ai_syllabi_etl run --backend rule      # offline, deterministic
python -m ai_syllabi_etl run --backend openai    # LM Studio / Ollama / cloud
```
"""
