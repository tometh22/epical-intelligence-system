"""Generate the Vista HTML report from the outputs of run_vista_pipeline.

Usage:
    python scripts/build_vista_html.py --run-dir outputs/vista/full
    python scripts/build_vista_html.py --run-dir outputs/vista/full \
        --input "<original YouScan CSV>"  # to compute YouScan vs classifier comparison
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.vista_html import build_vista_html  # noqa: E402


def _count_yc_candidatura(input_csv: Path, window_start: str, window_end: str) -> int:
    """Return how many mentions in the window were tagged 'Narrativa Candidatura' by YouScan."""
    if not input_csv.exists():
        return 0
    try:
        df = pd.read_csv(input_csv, low_memory=False)
    except Exception:
        return 0
    if "Narrativa Candidatura" not in df.columns or "Fecha" not in df.columns:
        return 0
    dt = pd.to_datetime(df["Fecha"], errors="coerce", dayfirst=True)
    mask_window = (dt >= pd.Timestamp(window_start)) & (
        dt <= pd.Timestamp(window_end) + pd.Timedelta(hours=23, minutes=59, seconds=59)
    )
    sub = df[mask_window]
    tagged = sub["Narrativa Candidatura"].apply(
        lambda s: bool(s) and str(s).strip() not in ("", "nan", "None")
    )
    return int(tagged.sum())


def main() -> int:
    p = argparse.ArgumentParser(description="Build Vista HTML report from pipeline outputs")
    p.add_argument("--run-dir", type=Path, required=True,
                   help="Directory containing clasificadas.csv + metricas.json")
    p.add_argument("--input", type=Path, default=None,
                   help="Original YouScan CSV (used to count Narrativa Candidatura tag)")
    p.add_argument("--window-start", type=str, default="2026-04-24")
    p.add_argument("--window-end", type=str, default="2026-04-30")
    p.add_argument("--baseline-start", type=str, default="2026-03-25")
    p.add_argument("--baseline-end", type=str, default="2026-04-23")
    p.add_argument("--output", type=Path, default=None,
                   help="Output HTML path. Defaults to <run-dir>/vista_report.html")
    args = p.parse_args()

    run_dir: Path = args.run_dir
    metrics_path = run_dir / "metricas.json"
    classified_path = run_dir / "clasificadas.csv"
    rancia_path = run_dir / "rancia_filtradas.csv"

    if not metrics_path.exists() or not classified_path.exists():
        print(f"ERROR: missing files in {run_dir}: need metricas.json and clasificadas.csv")
        return 1

    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    df_classified = pd.read_csv(classified_path, low_memory=False)

    # Pipeline stats from the run section of metricas.json + classified DF + rancia
    run_meta = metrics.get("run", {})
    classifier_stats = (run_meta.get("classifier_stats_window") or {}) | {}
    classifier_stats_b = run_meta.get("classifier_stats_baseline") or {}

    rancia_count = 0
    if rancia_path.exists():
        try:
            rancia_count = len(pd.read_csv(rancia_path, low_memory=False))
        except Exception:
            rancia_count = 0

    total_classified = (
        classifier_stats.get("classified", 0)
        + (classifier_stats_b.get("classified", 0) if isinstance(classifier_stats_b, dict) else 0)
    )

    # Pipeline stats fed into the methodology slide. We don't know the raw
    # pre-filter row count here unless --input is provided; estimate from
    # in-period + rancia.
    total_in_period = (
        run_meta.get("classifier_stats_window", {}).get("to_classify", 0)
        + (run_meta.get("classifier_stats_baseline") or {}).get("to_classify", 0)
        + rancia_count
    )
    pipeline_stats = {
        "total_raw": total_in_period,  # best-effort; replaced below if --input present
        "total_in_period": total_in_period,
        "rancia_filtered": rancia_count,
        "classified": total_classified,
    }

    yc_candidatura = 0
    if args.input is not None:
        if args.input.exists():
            try:
                df_raw = pd.read_csv(args.input, low_memory=False)
                pipeline_stats["total_raw"] = len(df_raw)
            except Exception as e:
                print(f"WARN: could not read --input ({e}); skipping raw count")
        yc_candidatura = _count_yc_candidatura(args.input, args.window_start, args.window_end)

    period_window = f"{args.window_start} — {args.window_end}"
    period_baseline = f"{args.baseline_start} — {args.baseline_end}" if args.baseline_start else None

    output_path = args.output or (run_dir / "vista_report.html")

    build_vista_html(
        metrics,
        df_classified,
        output_path,
        period_window=period_window,
        period_baseline=period_baseline,
        pipeline_stats=pipeline_stats,
        yc_candidatura_count=yc_candidatura,
    )

    print(f"\n✅ HTML generated: {output_path}")
    print(f"   Open: file://{output_path.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
