"""Aggregations over a Vista-classified DataFrame.

`compute_vista_metrics` is the single public entry point. Output schema
is stable so it can be serialized to JSON and consumed downstream.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional

import pandas as pd

from agents.shared.logger import get_logger

logger = get_logger("vista")


AXES = (0, 1, 2, 3)


# ──────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────

def _safe_pct(num: float, den: float) -> float:
    if den is None or den == 0:
        return 0.0
    return round(num / den * 100, 1)


def _coerce_axis_column(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with eje_narrativo coerced to int (NaN → 0)."""
    df = df.copy()
    if "eje_narrativo" not in df.columns:
        raise ValueError(
            "compute_vista_metrics: input DataFrame must have an 'eje_narrativo' column. "
            "Run classify_vista_dataframe first."
        )
    df["eje_narrativo"] = pd.to_numeric(df["eje_narrativo"], errors="coerce").fillna(0).astype(int)
    return df


def _volume_by_axis(df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
    total = len(df)
    out: Dict[str, Dict[str, Any]] = {}
    for axis in AXES:
        count = int((df["eje_narrativo"] == axis).sum())
        out[str(axis)] = {"count": count, "pct": _safe_pct(count, total)}
    return out


def _timeline_by_axis(df: pd.DataFrame) -> Dict[str, list]:
    out: Dict[str, list] = {str(a): [] for a in AXES}
    if "date" not in df.columns:
        return out

    df_dated = df.copy()
    df_dated["date"] = pd.to_datetime(df_dated["date"], errors="coerce", dayfirst=True)
    df_dated = df_dated.dropna(subset=["date"])
    if df_dated.empty:
        return out
    df_dated["date_only"] = df_dated["date"].dt.date

    for axis in AXES:
        sub = df_dated[df_dated["eje_narrativo"] == axis]
        if sub.empty:
            continue
        daily = sub.groupby("date_only").size().sort_index()
        out[str(axis)] = [
            {"date": str(d), "mentions": int(c)} for d, c in daily.items()
        ]
    return out


def _top_framings_by_axis(df: pd.DataFrame, top_n: int = 10) -> Dict[str, list]:
    out: Dict[str, list] = {str(a): [] for a in AXES}
    if "framing_dominante" not in df.columns:
        return out

    for axis in AXES:
        sub = df[df["eje_narrativo"] == axis]
        if sub.empty:
            continue
        framings = sub["framing_dominante"].astype(str).str.strip()
        framings = framings[framings != ""]
        if framings.empty:
            continue
        counts = framings.value_counts().head(top_n)
        total_with_framing = len(framings)
        out[str(axis)] = [
            {"framing": str(f), "count": int(c), "pct": _safe_pct(int(c), total_with_framing)}
            for f, c in counts.items()
        ]
    return out


def _sentiment_by_axis(df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
    """Sentiment percentages per axis. Lenient with sentiment label variants
    (positivo/positive, negativo/negative, neutral/neutro)."""
    canonical = {
        "positivo": "positivo", "positive": "positivo",
        "negativo": "negativo", "negative": "negativo",
        "neutral": "neutral", "neutro": "neutral",
    }
    out: Dict[str, Dict[str, Any]] = {}
    has_sent = "sentiment" in df.columns
    for axis in AXES:
        sub = df[df["eje_narrativo"] == axis]
        n = len(sub)
        entry: Dict[str, Any] = {
            "n": int(n),
            "positivo": 0.0, "negativo": 0.0, "neutral": 0.0,
        }
        if has_sent and n > 0:
            counts = sub["sentiment"].astype(str).str.lower().str.strip().value_counts()
            for raw_label, raw_count in counts.items():
                key = canonical.get(raw_label)
                if key is None:
                    continue
                entry[key] = round(entry[key] + _safe_pct(int(raw_count), n), 1)
        out[str(axis)] = entry
    return out


def _platform_by_axis(df: pd.DataFrame) -> Dict[str, list]:
    out: Dict[str, list] = {str(a): [] for a in AXES}
    pcol = "platform" if "platform" in df.columns else None
    if pcol is None:
        return out
    for axis in AXES:
        sub = df[df["eje_narrativo"] == axis]
        n = len(sub)
        if n == 0:
            continue
        counts = sub[pcol].astype(str).str.strip().value_counts()
        out[str(axis)] = [
            {"platform": str(p), "count": int(c), "pct": _safe_pct(int(c), n)}
            for p, c in counts.items()
        ]
    return out


def _baseline_comparison(df_window: pd.DataFrame, df_baseline: pd.DataFrame) -> Dict[str, Any]:
    """Compare window vs baseline: per-axis volume deltas + framings that are
    new or substantially amplified in the window."""
    by_axis: Dict[str, Dict[str, Any]] = {}
    for axis in AXES:
        w = int((df_window["eje_narrativo"] == axis).sum())
        b = int((df_baseline["eje_narrativo"] == axis).sum())
        if b > 0:
            delta_pct = round((w - b) / b * 100, 1)
            label = "stable" if abs(delta_pct) < 20 else ("growing" if delta_pct > 0 else "shrinking")
        else:
            delta_pct = None
            label = "new" if w > 0 else "absent"
        by_axis[str(axis)] = {
            "window_count": w,
            "baseline_count": b,
            "delta_pct": delta_pct,
            "label": label,
        }

    # Top "new" framings: framings that surface in the window with count >= 3
    # and at most one occurrence in the baseline.
    new_framings: list = []
    if "framing_dominante" in df_window.columns:
        w_f = df_window["framing_dominante"].astype(str).str.strip()
        w_counts = w_f[w_f != ""].value_counts()

        b_counts = pd.Series(dtype=int)
        if "framing_dominante" in df_baseline.columns:
            b_f = df_baseline["framing_dominante"].astype(str).str.strip()
            b_counts = b_f[b_f != ""].value_counts()

        for framing, w_count in w_counts.items():
            w_count = int(w_count)
            if w_count < 3:
                continue
            b_count = int(b_counts.get(framing, 0))
            if b_count > 1:
                continue
            new_framings.append({
                "framing": str(framing),
                "window_count": w_count,
                "baseline_count": b_count,
            })
        new_framings.sort(key=lambda x: x["window_count"], reverse=True)

    return {
        "by_axis": by_axis,
        "top_new_framings": new_framings[:15],
    }


def _empty_metrics() -> Dict[str, Any]:
    return {
        "total_mentions": 0,
        "by_axis": {str(a): {"count": 0, "pct": 0.0} for a in AXES},
        "timeline_by_axis": {str(a): [] for a in AXES},
        "top_framings_by_axis": {str(a): [] for a in AXES},
        "sentiment_by_axis": {
            str(a): {"n": 0, "positivo": 0.0, "negativo": 0.0, "neutral": 0.0}
            for a in AXES
        },
        "platform_by_axis": {str(a): [] for a in AXES},
        "baseline_comparison": None,
    }


# ──────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────

def compute_vista_metrics(
    df_window: pd.DataFrame,
    *,
    df_baseline: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    """Compute the aggregated metrics dict for a Vista-classified DataFrame.

    Args:
        df_window: Mentions in the analysis window (24/4–5/5/2026).
            Must have an 'eje_narrativo' column. Optional columns used:
            date, framing_dominante, sentiment, platform.
        df_baseline: Optional baseline frame (e.g. 30 days previous to the
            window). Same schema requirement. If provided, the result
            includes a `baseline_comparison` block; otherwise it is null.

    Returns:
        Stable dict described in the module docstring.
    """
    if df_window is None or df_window.empty:
        logger.info("compute_vista_metrics: empty window frame — returning empty metrics")
        return _empty_metrics()

    df_w = _coerce_axis_column(df_window)

    metrics: Dict[str, Any] = {
        "total_mentions": int(len(df_w)),
        "by_axis": _volume_by_axis(df_w),
        "timeline_by_axis": _timeline_by_axis(df_w),
        "top_framings_by_axis": _top_framings_by_axis(df_w, top_n=10),
        "sentiment_by_axis": _sentiment_by_axis(df_w),
        "platform_by_axis": _platform_by_axis(df_w),
        "baseline_comparison": None,
    }

    if df_baseline is not None and not df_baseline.empty:
        df_b = _coerce_axis_column(df_baseline)
        metrics["baseline_comparison"] = _baseline_comparison(df_w, df_b)

    logger.info(
        "compute_vista_metrics: %d mentions → axis counts %s",
        metrics["total_mentions"],
        {k: v["count"] for k, v in metrics["by_axis"].items()},
    )

    return metrics
