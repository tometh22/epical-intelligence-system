"""End-to-end runner for the Vista narrative pipeline.

Usage:
    python scripts/run_vista_pipeline.py \
        --input <pre-classified CSV or YouScan-native CSV> \
        --output-dir outputs/vista \
        [--baseline <baseline CSV>] \
        [--window-start 2026-04-24] [--window-end 2026-05-05] \
        [--baseline-start 2026-03-25] [--baseline-end 2026-04-23] \
        [--no-ai] [--limit N]

Produces:
    <output-dir>/clasificadas.csv         — all kept mentions with eje + framing
    <output-dir>/rancia_filtradas.csv     — mentions flagged as rancia (kept for transparency)
    <output-dir>/metricas.json            — aggregated metrics
    <output-dir>/summary.md               — human-readable summary
    <output-dir>/run.log                  — log copy

Accepts both the canonical post-Railway schema (text, sentiment, ...)
and a raw YouScan export (Fecha, Texto, Sentimiento, ...). The latter is
auto-normalized in `_load_csv`.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agents.shared.logger import get_logger  # noqa: E402
from pipeline.rancia_filter import apply_rancia_filter  # noqa: E402
from pipeline.vista_classifier import classify_vista_dataframe  # noqa: E402
from pipeline.vista_metrics import AXES, compute_vista_metrics  # noqa: E402

logger = get_logger("vista")


# ──────────────────────────────────────────────────────────────────────
# CSV loading and column normalization
# ──────────────────────────────────────────────────────────────────────

# Maps YouScan-native Spanish column names → canonical schema.
YOUSCAN_TO_CANONICAL = {
    "Fecha": "date",
    "Texto": "text",
    "Sentimiento": "sentiment",
    "Autor": "author",
    "Fuente": "platform",
    "Engagement": "engagement",
    "Me gusta": "likes",
    "Comentarios": "comments",
    "Republicaciones": "shares",
    "Visualizaciones": "views",
    "Alcance potencial": "reach",
    "Suscriptores": "reach",
    "Suscriptores del lugar de publicación": "reach",
    "País": "country",
    "URL": "url",
    "URL de la mención": "url",
    "Link": "url",
    "Idioma": "language",
}

CANONICAL_OPTIONAL_COLS = (
    "date", "text", "sentiment", "sentiment_toward", "relevance",
    "platform", "author", "engagement", "likes", "comments",
    "shares", "reach", "actor", "data_source",
)


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Rename YouScan-native columns to the canonical schema. Idempotent."""
    rename_map = {}
    for raw, canonical in YOUSCAN_TO_CANONICAL.items():
        if raw in df.columns and canonical not in df.columns:
            rename_map[raw] = canonical
    if rename_map:
        logger.info("Normalizing %d YouScan columns: %s", len(rename_map), rename_map)
        df = df.rename(columns=rename_map)

    # Lowercase variants
    lower_map = {c: c.lower() for c in df.columns if c != c.lower() and c.lower() in CANONICAL_OPTIONAL_COLS}
    if lower_map:
        df = df.rename(columns=lower_map)

    return df


def _load_csv(path: Path, *, date_filter: Optional[tuple[str, str]] = None,
              limit: Optional[int] = None) -> pd.DataFrame:
    """Load a CSV and normalize columns. Optionally filter by date range / limit."""
    if not path.exists():
        raise FileNotFoundError(f"Input not found: {path}")

    logger.info("Loading %s (%.1f MB)", path.name, path.stat().st_size / 1_000_000)
    df = pd.read_csv(path, low_memory=False)
    logger.info("Loaded %d rows × %d cols", len(df), len(df.columns))

    df = _normalize_columns(df)

    if "text" not in df.columns:
        raise ValueError(
            f"{path.name} has no 'text' (or 'Texto') column. Columns present: "
            f"{sorted(df.columns.tolist())[:20]}..."
        )

    # Drop empty-text rows
    before = len(df)
    df = df[df["text"].astype(str).str.strip() != ""]
    df = df.dropna(subset=["text"]).reset_index(drop=True)
    if len(df) < before:
        logger.info("Dropped %d empty-text rows", before - len(df))

    # Date filter — inclusive on both ends (treat YYYY-MM-DD as full days)
    if date_filter and "date" in df.columns:
        start, end = date_filter
        dt = pd.to_datetime(df["date"], errors="coerce", dayfirst=True)
        start_ts = pd.Timestamp(start)
        end_ts = pd.Timestamp(end) + pd.Timedelta(hours=23, minutes=59, seconds=59)
        mask = (dt >= start_ts) & (dt <= end_ts)
        before = len(df)
        df = df[mask].reset_index(drop=True)
        logger.info("Date filter %s..%s: %d → %d rows", start, end, before, len(df))

    if limit is not None and limit > 0:
        df = df.head(limit).reset_index(drop=True)
        logger.info("Limit applied: %d rows", len(df))

    return df


# ──────────────────────────────────────────────────────────────────────
# Output writers
# ──────────────────────────────────────────────────────────────────────

def _write_csv(df: pd.DataFrame, path: Path) -> None:
    df.to_csv(path, index=False)
    logger.info("Wrote %s (%d rows, %.1f KB)", path.name, len(df), path.stat().st_size / 1024)


def _write_json(data: dict, path: Path) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Wrote %s (%.1f KB)", path.name, path.stat().st_size / 1024)


AXIS_LABELS = {
    0: "Ninguno de los tres ejes",
    1: "Candidato de este estilo",
    2: "Nuevo empresariado",
    3: "Rol del empresariado en esta época",
}


def _format_summary_md(
    metrics: dict,
    *,
    input_count: int,
    rancia_count: int,
    classified_count: int,
    parse_errors: int,
    skipped_existing: int,
    window: Optional[tuple[str, str]],
    baseline: Optional[tuple[str, str]],
    no_ai: bool,
) -> str:
    lines = [f"# Vista pipeline — Resumen"]
    lines.append("")
    lines.append(f"_Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_")
    lines.append("")
    if window:
        lines.append(f"- **Ventana:** {window[0]} a {window[1]}")
    if baseline:
        lines.append(f"- **Baseline:** {baseline[0]} a {baseline[1]}")
    lines.append(f"- **Total entrante:** {input_count:,} menciones")
    lines.append(f"- **Filtradas como rancia:** {rancia_count:,} ({rancia_count / max(input_count, 1) * 100:.1f}%)")
    lines.append(f"- **Clasificadas:** {classified_count:,}")
    if skipped_existing:
        lines.append(f"- **Skipped (ya tenían eje):** {skipped_existing:,}")
    if parse_errors:
        lines.append(f"- **Parse errors:** {parse_errors:,}")
    if no_ai:
        lines.append("- **Modo:** `--no-ai` (clasificación AI saltada)")
    lines.append("")

    # Volumen por eje
    lines.append("## Volumen por eje narrativo")
    lines.append("")
    lines.append("| Eje | Etiqueta | Mentions | % |")
    lines.append("|-----|----------|---------:|--:|")
    for axis in AXES:
        v = metrics["by_axis"][str(axis)]
        lines.append(f"| {axis} | {AXIS_LABELS[axis]} | {v['count']:,} | {v['pct']}% |")
    lines.append("")

    # Top framings por eje (1, 2, 3 — saltamos 0)
    lines.append("## Top framings por eje")
    lines.append("")
    for axis in (1, 2, 3):
        framings = metrics["top_framings_by_axis"].get(str(axis), [])
        lines.append(f"### Eje {axis} — {AXIS_LABELS[axis]}")
        if not framings:
            lines.append("_(sin framings clasificados)_")
        else:
            for f in framings[:5]:
                lines.append(f"- **{f['framing']}** — {f['count']} ({f['pct']}%)")
        lines.append("")

    # Sentiment por eje
    lines.append("## Sentiment por eje")
    lines.append("")
    lines.append("| Eje | n | positivo | negativo | neutral |")
    lines.append("|-----|--:|---------:|---------:|--------:|")
    for axis in AXES:
        s = metrics["sentiment_by_axis"][str(axis)]
        lines.append(f"| {axis} | {s['n']} | {s['positivo']}% | {s['negativo']}% | {s['neutral']}% |")
    lines.append("")

    # Plataforma por eje (top 3 por eje)
    lines.append("## Plataforma por eje (top 3)")
    lines.append("")
    for axis in AXES:
        plats = metrics["platform_by_axis"].get(str(axis), [])
        if not plats:
            continue
        lines.append(f"- **Eje {axis}:** " + ", ".join(
            f"{p['platform']} ({p['count']})" for p in plats[:3]
        ))
    lines.append("")

    # Comparación baseline
    bc = metrics.get("baseline_comparison")
    if bc:
        lines.append("## Comparación vs baseline")
        lines.append("")
        lines.append("| Eje | Ventana | Baseline | Δ% | Etiqueta |")
        lines.append("|-----|--------:|---------:|---:|---------|")
        for axis in AXES:
            row = bc["by_axis"][str(axis)]
            delta = "—" if row["delta_pct"] is None else f"{row['delta_pct']}%"
            lines.append(
                f"| {axis} | {row['window_count']} | {row['baseline_count']} | "
                f"{delta} | {row['label']} |"
            )
        lines.append("")
        if bc["top_new_framings"]:
            lines.append("### Framings nuevos / amplificados en la ventana")
            for f in bc["top_new_framings"][:10]:
                lines.append(
                    f"- **{f['framing']}** — ventana={f['window_count']}, baseline={f['baseline_count']}"
                )
            lines.append("")
    return "\n".join(lines) + "\n"


# ──────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Vista narrative pipeline runner")
    p.add_argument("--input", type=Path, required=True,
                   help="Path to input CSV (canonical post-Railway schema or raw YouScan)")
    p.add_argument("--output-dir", type=Path, required=True,
                   help="Directory to write all outputs into (created if missing)")
    p.add_argument("--baseline", type=Path,
                   help="Optional separate baseline CSV. If omitted but "
                        "--baseline-start/--baseline-end are given, the same input "
                        "is sliced by date.")
    p.add_argument("--window-start", type=str,
                   help="ISO date for window start (e.g. 2026-04-24)")
    p.add_argument("--window-end", type=str,
                   help="ISO date for window end (e.g. 2026-05-05)")
    p.add_argument("--baseline-start", type=str,
                   help="ISO date for baseline start")
    p.add_argument("--baseline-end", type=str,
                   help="ISO date for baseline end")
    p.add_argument("--no-ai", action="store_true",
                   help="Skip Haiku classification — useful to validate parsing/rancia quickly")
    p.add_argument("--limit", type=int, default=None,
                   help="Process only the first N rows (smoke test)")
    p.add_argument("--batch-size", type=int, default=25,
                   help="Mentions per Haiku call (default: 25)")
    return p.parse_args()


def _print_progress(batch_idx: int, total_batches: int) -> None:
    pct = batch_idx / total_batches * 100
    print(f"  [classifier] batch {batch_idx}/{total_batches} ({pct:.0f}%)")


def main() -> int:
    args = _parse_args()
    t0 = time.time()

    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    window_dates = None
    if args.window_start and args.window_end:
        window_dates = (args.window_start, args.window_end)

    baseline_dates = None
    if args.baseline_start and args.baseline_end:
        baseline_dates = (args.baseline_start, args.baseline_end)

    # ── Load window data ────────────────────────────────────────────
    print(f"\n=== Loading window CSV ===")
    df_window_raw = _load_csv(
        args.input,
        date_filter=window_dates,
        limit=args.limit,
    )

    # ── Load baseline (separate file or sliced from same input) ─────
    df_baseline_raw: Optional[pd.DataFrame] = None
    if args.baseline is not None:
        print(f"\n=== Loading baseline CSV ===")
        df_baseline_raw = _load_csv(
            args.baseline,
            date_filter=baseline_dates,
            limit=args.limit,
        )
    elif baseline_dates is not None:
        print(f"\n=== Slicing baseline from input ===")
        df_baseline_raw = _load_csv(
            args.input,
            date_filter=baseline_dates,
            limit=args.limit,
        )

    # ── Rancia filter ───────────────────────────────────────────────
    print(f"\n=== Rancia filter ===")
    df_window, df_rancia_window = apply_rancia_filter(df_window_raw)
    df_baseline = None
    df_rancia_baseline = pd.DataFrame()
    if df_baseline_raw is not None:
        df_baseline, df_rancia_baseline = apply_rancia_filter(df_baseline_raw)

    rancia_combined = pd.concat([df_rancia_window, df_rancia_baseline], ignore_index=True) \
        if not df_rancia_baseline.empty else df_rancia_window

    # ── Classify ────────────────────────────────────────────────────
    print(f"\n=== Classification ===")
    if args.no_ai:
        print("  --no-ai set: skipping Haiku, marking all rows eje_narrativo=0")
        df_window["eje_narrativo"] = 0
        df_window["framing_dominante"] = ""
        df_window["eje_confianza"] = 0.0
        df_window["eje_razon"] = "ai_skipped"
        if df_baseline is not None:
            df_baseline["eje_narrativo"] = 0
            df_baseline["framing_dominante"] = ""
            df_baseline["eje_confianza"] = 0.0
            df_baseline["eje_razon"] = "ai_skipped"
        stats_window = {
            "total_rows": len(df_window), "to_classify": 0,
            "skipped_already_classified": 0, "classified": 0, "parse_errors": 0,
        }
        stats_baseline = stats_window.copy()
    else:
        df_window, stats_window = classify_vista_dataframe(
            df_window, batch_size=args.batch_size, on_progress=_print_progress,
        )
        if df_baseline is not None:
            print(f"\n=== Classifying baseline ===")
            df_baseline, stats_baseline = classify_vista_dataframe(
                df_baseline, batch_size=args.batch_size, on_progress=_print_progress,
            )
        else:
            stats_baseline = {}

    # ── Metrics ─────────────────────────────────────────────────────
    print(f"\n=== Metrics ===")
    metrics = compute_vista_metrics(df_window, df_baseline=df_baseline)

    # Add run metadata
    metrics["run"] = {
        "input": str(args.input),
        "output_dir": str(output_dir),
        "window": {"start": args.window_start, "end": args.window_end},
        "baseline": {"start": args.baseline_start, "end": args.baseline_end},
        "no_ai": args.no_ai,
        "limit": args.limit,
        "batch_size": args.batch_size,
        "elapsed_seconds": round(time.time() - t0, 1),
        "classifier_stats_window": stats_window,
        "classifier_stats_baseline": stats_baseline,
        "rancia_window_count": int(len(df_rancia_window)),
        "rancia_baseline_count": int(len(df_rancia_baseline)),
    }

    # ── Outputs ─────────────────────────────────────────────────────
    print(f"\n=== Writing outputs to {output_dir} ===")

    # Combined classified frame: window + baseline (with a label)
    df_window_out = df_window.copy()
    df_window_out["data_period"] = "window"
    classified_frames = [df_window_out]
    if df_baseline is not None:
        df_baseline_out = df_baseline.copy()
        df_baseline_out["data_period"] = "baseline"
        classified_frames.append(df_baseline_out)
    df_classified = pd.concat(classified_frames, ignore_index=True)

    _write_csv(df_classified, output_dir / "clasificadas.csv")
    _write_csv(rancia_combined, output_dir / "rancia_filtradas.csv")
    _write_json(metrics, output_dir / "metricas.json")

    summary_md = _format_summary_md(
        metrics,
        input_count=len(df_window_raw) + (len(df_baseline_raw) if df_baseline_raw is not None else 0),
        rancia_count=len(rancia_combined),
        classified_count=stats_window.get("classified", 0) + (stats_baseline.get("classified", 0) if isinstance(stats_baseline, dict) else 0),
        parse_errors=stats_window.get("parse_errors", 0) + (stats_baseline.get("parse_errors", 0) if isinstance(stats_baseline, dict) else 0),
        skipped_existing=stats_window.get("skipped_already_classified", 0) + (stats_baseline.get("skipped_already_classified", 0) if isinstance(stats_baseline, dict) else 0),
        window=window_dates, baseline=baseline_dates, no_ai=args.no_ai,
    )
    (output_dir / "summary.md").write_text(summary_md, encoding="utf-8")
    logger.info("Wrote summary.md")

    # Copy log if it exists
    log_path = PROJECT_ROOT / "logs" / "vista.log"
    if log_path.exists():
        shutil.copy2(log_path, output_dir / "run.log")

    elapsed = time.time() - t0
    print(f"\n✅ Done in {elapsed:.1f}s")
    print(f"   Outputs:")
    for name in ("clasificadas.csv", "rancia_filtradas.csv", "metricas.json", "summary.md"):
        p = output_dir / name
        if p.exists():
            print(f"     {p}  ({p.stat().st_size / 1024:.1f} KB)")
    print(f"\n   Mentions per axis: {metrics['by_axis']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
