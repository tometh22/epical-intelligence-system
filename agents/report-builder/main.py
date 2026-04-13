"""Main entry point for the Report Builder agent."""

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# Ensure project root is on sys.path for module imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.shared.logger import get_logger
from agents.shared.storage import save_json, save_run_status

import json as _json
from agents.report_builder.config import BASE_DIR
from agents.report_builder.merger import merge_sources
from agents.report_builder.metrics import (
    MetricsCalculator,
    calculate_metrics,
    detect_anomalies,
    calculate_actor_metrics,
    calculate_intersection_metrics,
)
from agents.report_builder.sentiment_classifier import reclassify_sentiment
from agents.report_builder.classify_actors import classify_actors
from agents.report_builder.topics import detect_topic_clusters, format_topic_summary
from agents.report_builder.sampler import build_relevance_sample
from agents.report_builder.report_generator import generate_report_draft
from agents.report_builder.docx_builder import build_report_docx
from agents.report_builder.html_builder import build_report_html as _build_report_html_v1
from agents.report_builder.html_builder_v2 import build_report_html as _build_report_html_v2
from agents.report_builder.qa_auditor import run_qa_audit

logger = get_logger("report-builder")

AGENT_NAME = "report-builder"
CONFIG_PATH = BASE_DIR / "config" / "report_config.json"


def _load_report_config() -> Dict[str, Any]:
    """Load report_config.json if it exists, return empty dict otherwise."""
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return _json.load(f)
        except Exception:
            pass
    return {}


def run_report_builder(
    input_files: Union[Union[str, Path], List[Union[str, Path]]],
    client_name: str,
    period: str,
    source_labels: Optional[List[str]] = None,
    previous_report_path: Optional[Union[str, Path]] = None,
    logo_path: Optional[Union[str, Path]] = None,
    theme: str = "",
    brand_color: str = "",
    report_type: str = "",
) -> Dict[str, Any]:
    """Run the full report builder pipeline.

    Args:
        input_files: Path or list of paths to CSV/Excel/zip exports.
        client_name: Client identifier.
        period: Reporting period description (e.g. "Marzo 2026").
        source_labels: Optional labels for each input file (e.g. ["youscan", "influencer"]).
        previous_report_path: Optional path to a previous report for comparison.

    Returns:
        Dict with output paths and summary information.
    """
    # Load config defaults — CLI/API params override config file values
    cfg = _load_report_config()
    if not theme:
        theme = cfg.get("theme", "dark")
    if not brand_color:
        brand_color = cfg.get("brand_color", "#FF1B6B")
    if not report_type:
        report_type = cfg.get("report_type", "crisis")
    if not logo_path:
        cfg_logo = cfg.get("client_logo_path", "")
        if cfg_logo and (BASE_DIR / cfg_logo).exists():
            logo_path = str(BASE_DIR / cfg_logo)

    logger.info("Config: theme=%s, brand_color=%s, report_type=%s, logo=%s",
                theme, brand_color, report_type, logo_path or "none")

    # Normalize input_files to a list
    if isinstance(input_files, (str, Path)):
        input_files = [input_files]
    file_paths = [Path(f) for f in input_files]

    try:
        # 1. Update run status to running
        save_run_status(AGENT_NAME, "running", {
            "client": client_name,
            "period": period,
            "input_files": [str(f) for f in file_paths],
        })
        logger.info(
            "Starting report builder for client '%s', period '%s', %d input file(s)",
            client_name, period, len(file_paths),
        )

        # 2. Merge and normalize all input files
        logger.info("Merging %d input file(s)...", len(file_paths))
        df_clean, data_quality_issues, source_counts = merge_sources(
            file_paths, source_labels=source_labels,
        )

        if df_clean.empty:
            raise ValueError("No data remaining after merging and cleaning. Check input files and column mappings.")

        logger.info("Merged dataset: %d rows from %d source(s)", len(df_clean), len(source_counts))

        # 2b. Sentiment reclassification
        logger.info("Running sentiment reclassification...")
        df_clean, reclass_stats = reclassify_sentiment(df_clean, use_ai=True)
        data_quality_issues.append(
            f"Sentiment reclassification: rules={reclass_stats.get('rules', 0)}, "
            f"ai={reclass_stats.get('ai', 0)}, "
            f"remaining_unclassified={reclass_stats.get('remaining', 0)} "
            f"({reclass_stats.get('remaining_pct', 0)}%)"
        )

        # 2c. Actor sub-classification
        logger.info("Running actor sub-classification...")
        df_clean, actor_class_stats = classify_actors(df_clean, use_ai=True)
        if actor_class_stats.get("original_otros", 0) > 0:
            data_quality_issues.append(
                f"Actor classification: rules={actor_class_stats.get('rules', 0)}, "
                f"ai={actor_class_stats.get('ai', 0)}, "
                f"remaining_otros={actor_class_stats.get('remaining_otros', 0)} "
                f"({actor_class_stats.get('remaining_otros_pct', 0)}%)"
            )

        # 3. Calculate metrics (combined)
        logger.info("Calculating metrics...")
        metrics = calculate_metrics(df_clean)

        # Add source breakdown to metrics
        metrics["source_breakdown"] = source_counts

        # 3b. Calculate actor-separated metrics
        logger.info("Calculating actor-separated metrics...")
        actor_metrics = calculate_actor_metrics(df_clean)
        metrics["actor_metrics"] = {
            k: v for k, v in actor_metrics.items() if k != "combined"
        }
        metrics["reclassification_stats"] = reclass_stats

        # Add actor sub-category breakdown
        if "actor_subcategory" in df_clean.columns:
            subcat_counts = df_clean["actor_subcategory"].value_counts().to_dict()
            metrics["actor_subcategory_breakdown"] = {str(k): int(v) for k, v in subcat_counts.items() if str(k).strip()}

        # 3c. Calculate intersection metrics
        logger.info("Calculating intersection metrics...")
        intersection = calculate_intersection_metrics(df_clean)
        metrics["intersection"] = intersection

        # 3d. New spec metrics via MetricsCalculator
        logger.info("Computing advanced metrics (engagement, timeline, reach, spikes, criticism)...")
        mc = MetricsCalculator(df_clean)
        metrics["engagement_by_platform"] = mc.compute_engagement_by_platform()
        timeline = mc.compute_timeline()
        metrics["timeline"] = timeline
        metrics["spikes"] = mc.detect_spikes(daily_data=timeline.get("daily"))
        metrics["reach_deduplicated"] = mc.compute_reach_deduplicated()
        metrics["tangential_analysis"] = mc.compute_tangential_analysis()
        metrics["brand_criticism"] = mc.categorize_brand_criticism(
            brand_name=cfg.get("primary_brand", client_name),
        )

        # 4. Detect anomalies
        logger.info("Detecting anomalies...")
        anomalies = detect_anomalies(df_clean, metrics)

        # 5. Detect topic clusters (runs on ALL mentions)
        logger.info("Detecting topic clusters...")
        topic_clusters = detect_topic_clusters(df_clean)
        topic_summary = format_topic_summary(topic_clusters)

        # Add topic info to metrics for downstream use
        metrics["topic_clusters"] = [
            {"label": c["label"], "keywords": c["keywords"],
             "mention_count": c["mention_count"], "percentage": c["percentage"]}
            for c in topic_clusters
        ]

        # 5b. Co-occurrence graph from topic keywords
        all_concepts = []
        for c in topic_clusters:
            all_concepts.extend(c.get("keywords", [])[:3])
        # Add brand and actor names as concepts
        all_concepts.append(cfg.get("primary_brand", client_name).lower())
        for actor_name_cfg in cfg.get("secondary_actors", []):
            all_concepts.append(actor_name_cfg.lower())
        all_concepts = list(dict.fromkeys(all_concepts))  # dedupe preserving order
        if all_concepts:
            logger.info("Computing co-occurrence graph with %d concepts...", len(all_concepts))
            metrics["cooccurrence"] = mc.compute_cooccurrence(all_concepts)

        # 6. Build topic-aware relevance sample for Claude
        logger.info("Building topic-aware relevance sample...")
        sample_mentions, sample_composition = build_relevance_sample(
            df_clean, metrics, topic_clusters=topic_clusters,
        )
        data_quality_issues.append(f"Sample composition: {sample_composition}")

        # 7. Generate report narrative via Claude
        logger.info("Generating report narrative...")
        report_text = generate_report_draft(
            client_name=client_name,
            period=period,
            metrics=metrics,
            anomalies=anomalies,
            sample_mentions=sample_mentions,
            data_quality_issues=data_quality_issues,
            topic_summary=topic_summary,
            report_type=report_type,
        )

        # 8. Build output paths
        date_str = date.today().isoformat()
        safe_client = client_name.replace(" ", "_").lower()
        output_dir = BASE_DIR / "outputs" / AGENT_NAME

        json_filename = f"{safe_client}_{date_str}.json"
        docx_filename = f"{safe_client}_{date_str}.docx"
        html_filename = f"{safe_client}_{date_str}.html"
        json_path = output_dir / json_filename
        docx_path = output_dir / docx_filename
        html_path = output_dir / html_filename

        # 8. Save JSON summary
        summary = {
            "client": client_name,
            "period": period,
            "generated_date": date_str,
            "input_files": [str(f) for f in file_paths],
            "source_counts": source_counts,
            "metrics": metrics,
            "anomalies": anomalies,
            "data_quality_issues": data_quality_issues,
            "sample_composition": sample_composition,
            "report_text": report_text,
        }
        save_json(summary, json_path)
        logger.info("JSON summary saved to %s", json_path)

        # 9. Build .docx
        logger.info("Building DOCX report...")
        metrics["anomalies_list"] = anomalies
        build_report_docx(
            client_name=client_name,
            period=period,
            report_text=report_text,
            metrics=metrics,
            output_path=docx_path,
        )

        # 10. Build .html (v2 — parametrized from v10 template)
        logger.info("Building HTML report (v2 builder)...")
        _build_report_html_v2(
            client_name=client_name,
            period=period,
            report_text=report_text,
            metrics=metrics,
            anomalies=anomalies,
            output_path=html_path,
            logo_path=logo_path,
            theme=theme,
            brand_color=brand_color,
            report_type=report_type,
            client_role=cfg.get("client_role", ""),
            client_logo_url=cfg.get("client_logo_url", ""),
        )

        # 11. Run QA audit
        logger.info("Running QA audit...")
        qa_filename = f"{safe_client}_{date_str}_QA_REPORT.html"
        qa_path = output_dir / qa_filename
        qa_result = run_qa_audit(
            report_text=report_text,
            metrics=metrics,
            client_name=client_name,
            period=period,
            output_path=qa_path,
            use_ai=True,
        )

        # 12. Update run status to completed
        result = {
            "json_path": str(json_path),
            "docx_path": str(docx_path),
            "html_path": str(html_path),
            "qa_file": str(qa_path),
            "qa_status": qa_result["qa_status"],
            "qa_errors": qa_result["qa_errors"],
            "qa_warnings": qa_result["qa_warnings"],
            "total_mentions": metrics["total_mentions"],
            "anomalies_count": len(anomalies),
            "source_counts": source_counts,
            "data_quality_issues": data_quality_issues,
        }
        save_run_status(AGENT_NAME, "completed", result)
        logger.info("Report builder completed. QA: %s (%d errors, %d warnings). Outputs: %s, %s, %s, %s",
                     qa_result["qa_status"], qa_result["qa_errors"], qa_result["qa_warnings"],
                     json_path, docx_path, html_path, qa_path)

        return result

    except Exception as e:
        logger.error("Report builder failed: %s", e, exc_info=True)
        save_run_status(AGENT_NAME, "error", {"error": str(e)})
        raise


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Epical Report Builder - Genera informes de inteligencia social"
    )
    parser.add_argument(
        "--input", required=True, nargs="+",
        help="Path(s) to YouScan/influencer CSV/Excel/zip export file(s)",
    )
    parser.add_argument(
        "--labels", nargs="*", default=None,
        help="Source labels for each input file (e.g. youscan influencer)",
    )
    parser.add_argument(
        "--client", required=True, help="Client name",
    )
    parser.add_argument(
        "--period", required=True, help='Reporting period (e.g. "Marzo 2026")',
    )
    parser.add_argument(
        "--previous-report", default=None, help="Path to a previous report for comparison",
    )
    parser.add_argument(
        "--logo", default=None, help="Path to client logo image (PNG/SVG/JPG) to embed in the report",
    )
    parser.add_argument(
        "--theme", default="dark", choices=["dark", "light"], help="Report theme: dark or light",
    )
    parser.add_argument(
        "--brand-color", default="#FF1B6B", help="Client brand color hex for light theme accent",
    )
    parser.add_argument(
        "--report-type", default="crisis", choices=["crisis", "campaign", "monitoring"],
        help="Report type mode: crisis, campaign, or monitoring",
    )

    args = parser.parse_args()

    result = run_report_builder(
        input_files=args.input,
        client_name=args.client,
        period=args.period,
        source_labels=args.labels,
        previous_report_path=args.previous_report,
        logo_path=args.logo,
        theme=args.theme,
        brand_color=args.brand_color,
        report_type=args.report_type,
    )

    print("\n--- Report Builder Complete ---")
    print(f"JSON output: {result['json_path']}")
    print(f"DOCX output: {result['docx_path']}")
    print(f"HTML output: {result['html_path']}")
    print(f"Total mentions: {result['total_mentions']}")
    print(f"Anomalies detected: {result['anomalies_count']}")
    if result.get("source_counts"):
        print("Source breakdown:")
        for src, count in result["source_counts"].items():
            print(f"  - {src}: {count} rows")
    if result["data_quality_issues"]:
        print("Data quality issues:")
        for issue in result["data_quality_issues"]:
            print(f"  - {issue}")


if __name__ == "__main__":
    main()
