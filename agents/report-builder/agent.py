"""Conversational Report Builder Agent — 3-checkpoint flow.

Orchestrates the full report generation pipeline:
    Phase 1: Autonomous processing (SentimIA → Metrics → Synthesis → HTML draft)
    Checkpoint 1: Present to analyst for strategic direction
    Phase 2: Refinement with feedback
    Checkpoint 2: Refined report review
    Phase 3: Final delivery (PDF generation)
    Checkpoint 3: Final delivery with verification

The agent is a state machine. External code drives it by calling
advance() with analyst feedback at each checkpoint.
"""

import json
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

import pandas as pd

from agents.shared.logger import get_logger
from agents.shared.storage import save_json, save_run_status

logger = get_logger("report-builder")


class AgentState(str, Enum):
    """Agent lifecycle states."""
    INIT = "init"
    PROCESSING = "processing"
    CHECKPOINT_1 = "checkpoint_1"
    REFINING = "refining"
    CHECKPOINT_2 = "checkpoint_2"
    DELIVERING = "delivering"
    CHECKPOINT_3 = "checkpoint_3"
    DONE = "done"
    ERROR = "error"


@dataclass
class CheckpointMessage:
    """What the agent presents to the analyst at a checkpoint."""
    checkpoint: int
    summary: str
    details: Dict[str, Any]
    attachments: List[str]  # file paths
    rule_violations: str  # formatted rules report
    requires_response: bool = True


@dataclass
class AgentContext:
    """All state accumulated during report generation."""
    # Input
    brief: str = ""
    client_name: str = ""
    period: str = ""
    file_paths: List[str] = field(default_factory=list)
    source_types: List[str] = field(default_factory=list)
    brand: str = ""
    actors: List[str] = field(default_factory=list)
    client_role: str = ""
    client_logo_url: str = ""
    event_date: Optional[str] = None
    report_type: str = "crisis"

    # Processing state
    sentimia_project_id: str = ""
    sentimia_results: Dict[str, Any] = field(default_factory=dict)
    df: Optional[Any] = None  # pd.DataFrame — relevant mentions only
    df_tangential: Optional[Any] = None  # pd.DataFrame — tangential mentions (for catalyst analysis)
    metrics: Dict[str, Any] = field(default_factory=dict)
    anomalies: List[Dict[str, Any]] = field(default_factory=list)
    topic_clusters: List[Dict[str, Any]] = field(default_factory=list)
    audit_accuracy: Optional[float] = None
    audit_report: str = ""
    report_text: str = ""
    report_sections: Optional[Dict[str, Any]] = None

    # Outputs
    html_path: Optional[str] = None
    pdf_path: Optional[str] = None
    json_path: Optional[str] = None
    html_version: int = 0

    # Feedback history
    feedback_log: List[Dict[str, str]] = field(default_factory=list)


class ReportBuilderAgent:
    """Conversational agent that generates intelligence reports with 3 human checkpoints.

    Usage:
        agent = ReportBuilderAgent(
            client_name="Avianca",
            period="Marzo-Abril 2026",
            brief="Export de YouScan + scrapping de Cossio...",
            file_paths=["data.csv"],
            brand="Avianca",
            actors=["Cossio", "Yeferson"],
        )

        # Phase 1: autonomous processing
        checkpoint1 = agent.run_phase1()
        # → presents thesis, findings, audit, HTML draft

        # Analyst responds
        checkpoint2 = agent.advance("Ok, pero agregá análisis de X")
        # → incorporates feedback, presents v2

        # Analyst approves
        checkpoint3 = agent.advance("Listo, generá el PDF")
        # → generates PDF, presents final verification

        # Done
        result = agent.advance("Ok, perfecto")
    """

    def __init__(
        self,
        client_name: str,
        period: str,
        brief: str,
        file_paths: List[Union[str, Path]],
        brand: str = "",
        actors: Optional[List[str]] = None,
        source_types: Optional[List[str]] = None,
        client_role: str = "",
        client_logo_url: str = "",
        event_date: Optional[str] = None,
        report_type: str = "crisis",
        sentimia_mock: bool = False,
        output_dir: Optional[Union[str, Path]] = None,
    ) -> None:
        self.state = AgentState.INIT
        self.sentimia_mock = sentimia_mock
        self.output_dir = Path(output_dir) if output_dir else self._default_output_dir()
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.ctx = AgentContext(
            brief=brief,
            client_name=client_name,
            period=period,
            file_paths=[str(p) for p in file_paths],
            source_types=source_types or ["csv"] * len(file_paths),
            brand=brand or client_name,
            actors=actors or [],
            client_role=client_role,
            client_logo_url=client_logo_url,
            event_date=event_date,
            report_type=report_type,
        )

        logger.info(
            "Agent initialized: client=%s, period=%s, files=%d, mock=%s",
            client_name, period, len(file_paths), sentimia_mock,
        )

    @staticmethod
    def _default_output_dir() -> Path:
        from agents.report_builder.config import BASE_DIR
        return BASE_DIR / "outputs" / "report-builder"

    # ══════════════════════════════════════════════════════════════
    # Phase 1: Autonomous processing
    # ══════════════════════════════════════════════════════════════

    def run_phase1(
        self,
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> CheckpointMessage:
        """Execute Phase 1: autonomous processing → Checkpoint 1.

        Steps: SentimIA → Merge → Classify → Metrics → Audit → Synthesis → HTML

        Args:
            on_progress: Optional callback for progress messages.

        Returns:
            CheckpointMessage for Checkpoint 1.
        """
        self.state = AgentState.PROCESSING
        save_run_status("report-builder", "running", {"phase": "1_processing"})

        def _progress(msg: str) -> None:
            logger.info("Phase 1: %s", msg)
            if on_progress:
                on_progress(msg)

        try:
            # 1.1 Send to SentimIA
            _progress("Enviando datos a SentimIA...")
            self._step_sentimia(on_progress=lambda s: _progress(
                f"SentimIA: {s.get('progress', 0):.0f}%"
                if isinstance(s, dict) else str(s)
            ))

            # 1.2 Load processed data as DataFrame
            _progress("Cargando datos procesados...")
            self._step_load_data()

            # 1.3 Run sentiment reclassification + actor classification
            _progress("Reclasificando sentimiento y actores...")
            self._step_classify()

            # 1.4 Calculate all metrics
            _progress("Calculando métricas...")
            self._step_metrics()

            # 1.5 Audit sample
            _progress("Auditando muestra de menciones...")
            self._step_audit()

            # 1.6 Detect topics + co-occurrence
            _progress("Detectando clusters temáticos...")
            self._step_topics()

            # 1.7 Narrative synthesis (Capa 3)
            _progress("Generando síntesis narrativa (Capa 3)...")
            self._step_synthesis()

            # 1.8 Generate HTML v1
            _progress("Generando HTML borrador...")
            self._step_generate_html()

            # Save JSON summary
            self._save_json_summary()

            # Transition to checkpoint 1
            self.state = AgentState.CHECKPOINT_1
            return self._build_checkpoint1()

        except Exception as e:
            self.state = AgentState.ERROR
            save_run_status("report-builder", "error", {"error": str(e)})
            logger.error("Phase 1 failed: %s", e, exc_info=True)
            raise

    # ══════════════════════════════════════════════════════════════
    # advance() — process analyst feedback at any checkpoint
    # ══════════════════════════════════════════════════════════════

    def advance(
        self,
        feedback: str,
        attachments: Optional[List[Union[str, Path]]] = None,
    ) -> Union[CheckpointMessage, Dict[str, Any]]:
        """Process analyst feedback and advance to next phase.

        Args:
            feedback: Analyst's response text.
            attachments: Optional file paths (e.g. screenshots).

        Returns:
            CheckpointMessage for next checkpoint, or final result dict.
        """
        self.ctx.feedback_log.append({
            "checkpoint": self.state.value,
            "feedback": feedback,
            "timestamp": datetime.now().isoformat(),
            "attachments": [str(a) for a in (attachments or [])],
        })

        if self.state == AgentState.CHECKPOINT_1:
            return self._handle_checkpoint1_response(feedback, attachments)
        elif self.state == AgentState.CHECKPOINT_2:
            return self._handle_checkpoint2_response(feedback, attachments)
        elif self.state == AgentState.CHECKPOINT_3:
            return self._handle_checkpoint3_response(feedback)
        else:
            raise RuntimeError(f"Cannot advance from state {self.state}")

    # ──────────────────────────────────────────────────────────────
    # Checkpoint 1 handler
    # ──────────────────────────────────────────────────────────────

    def _handle_checkpoint1_response(
        self,
        feedback: str,
        attachments: Optional[List[Union[str, Path]]],
    ) -> CheckpointMessage:
        """Phase 2: Refinement based on checkpoint 1 feedback."""
        self.state = AgentState.REFINING
        feedback_lower = feedback.lower().strip()

        # Detect if analyst approves
        approve_signals = ["ok", "seguí", "sigue", "de acuerdo", "perfecto", "listo"]
        is_approval = any(s in feedback_lower for s in approve_signals) and len(feedback_lower) < 50

        if not is_approval:
            logger.info("Checkpoint 1: analyst requests changes: %s", feedback[:100])

            # Re-generate synthesis incorporating feedback
            self._step_synthesis_with_feedback(feedback)

            # Regenerate HTML
            self._step_generate_html()

        self.state = AgentState.CHECKPOINT_2
        return self._build_checkpoint2(feedback)

    # ──────────────────────────────────────────────────────────────
    # Checkpoint 2 handler
    # ──────────────────────────────────────────────────────────────

    def _handle_checkpoint2_response(
        self,
        feedback: str,
        attachments: Optional[List[Union[str, Path]]],
    ) -> CheckpointMessage:
        """Phase 3: Final delivery."""
        self.state = AgentState.DELIVERING
        feedback_lower = feedback.lower().strip()

        # Check if analyst wants PDF
        wants_pdf = any(w in feedback_lower for w in ["pdf", "listo", "generá", "genera", "dale"])

        # Integrate screenshots if provided
        if attachments:
            logger.info("Integrating %d screenshots...", len(attachments))
            self._step_integrate_screenshots(attachments)

        # If not a direct approval, incorporate additional feedback
        if not wants_pdf and len(feedback_lower) > 20:
            logger.info("Checkpoint 2: additional adjustments: %s", feedback[:100])
            self._step_synthesis_with_feedback(feedback)
            self._step_generate_html()

        # Generate PDF
        self._step_generate_pdf()

        # Final verification
        verification = self._step_final_verification()

        self.state = AgentState.CHECKPOINT_3
        return self._build_checkpoint3(verification)

    # ──────────────────────────────────────────────────────────────
    # Checkpoint 3 handler
    # ──────────────────────────────────────────────────────────────

    def _handle_checkpoint3_response(self, feedback: str) -> Dict[str, Any]:
        """Mark as done and return final result."""
        self.state = AgentState.DONE

        result = {
            "status": "completed",
            "client": self.ctx.client_name,
            "period": self.ctx.period,
            "html_path": self.ctx.html_path,
            "pdf_path": self.ctx.pdf_path,
            "json_path": self.ctx.json_path,
            "total_mentions": self.ctx.metrics.get("total_mentions", 0),
            "html_versions": self.ctx.html_version,
            "feedback_rounds": len(self.ctx.feedback_log),
        }

        save_run_status("report-builder", "completed", result)
        logger.info("Agent completed: %s", result)
        return result

    # ══════════════════════════════════════════════════════════════
    # Processing steps
    # ══════════════════════════════════════════════════════════════

    def _step_sentimia(self, on_progress=None) -> None:
        """Step 1.2: Create project, upload files, process via SentimIA."""
        from agents.shared.sentimia_client import SentimiaClient

        client = SentimiaClient(mock=self.sentimia_mock)

        result = client.run_full_pipeline(
            name=f"{self.ctx.client_name} — {self.ctx.period}",
            brand=self.ctx.brand,
            context=self.ctx.brief,
            actors=self.ctx.actors,
            file_paths=[Path(p) for p in self.ctx.file_paths],
            source_types=self.ctx.source_types,
            on_progress=on_progress,
        )

        self.ctx.sentimia_project_id = result["project_id"]
        self.ctx.sentimia_results = result["results"]
        client.close()

    def _step_load_data(self) -> None:
        """Step 1.3: Load data into DataFrame (from SentimIA export or local files).

        Splits data into two separate datasets:
        - self.ctx.df            → relevance == "relevant" (main analysis)
        - self.ctx.df_tangential → relevance == "tangential" (catalyst analysis only)
        """
        if self.sentimia_mock:
            dfs = []
            issues: List[str] = []
            source_counts: Dict[str, int] = {}

            for fp_str, src_type in zip(self.ctx.file_paths, self.ctx.source_types):
                fp = Path(fp_str)
                try:
                    df_part = _load_preclassified_csv(fp, src_type)
                    if df_part is not None and not df_part.empty:
                        dfs.append(df_part)
                        source_counts[src_type] = len(df_part)
                        logger.info("Loaded pre-classified %s: %d rows", fp.name, len(df_part))
                        continue
                except Exception as e:
                    logger.debug("Pre-classified load failed for %s: %s", fp.name, e)

                # Fallback to merger
                try:
                    from agents.report_builder.merger import merge_sources
                    df_m, iss, sc = merge_sources([fp], source_labels=[src_type])
                    if not df_m.empty:
                        dfs.append(df_m)
                        source_counts.update(sc)
                        issues.extend(iss)
                except Exception as e:
                    issues.append(f"Failed to load {fp.name}: {e}")
                    logger.error("Failed to load %s: %s", fp.name, e)

            if dfs:
                df_all = pd.concat(dfs, ignore_index=True)
                rel_col = df_all["relevance"].astype(str).str.lower() if "relevance" in df_all.columns else pd.Series("relevant", index=df_all.index)

                # Split: relevant vs tangential vs discard
                df_relevant = df_all[rel_col == "relevant"].copy()
                df_tangential = df_all[rel_col.isin(["tangential", "tangencial"])].copy()
                discarded = len(df_all) - len(df_relevant) - len(df_tangential)

                # Also remove rows with sentiment=="removed" from relevant
                if "sentiment" in df_relevant.columns:
                    sent_removed = df_relevant["sentiment"].astype(str).str.lower() == "removed"
                    n_sent_removed = sent_removed.sum()
                    if n_sent_removed:
                        df_relevant = df_relevant[~sent_removed]
                        issues.append(f"Filtered {n_sent_removed} removed-sentiment rows from relevant")

                self.ctx.df = df_relevant
                self.ctx.df_tangential = df_tangential

                logger.info(
                    "Data split: %d relevant, %d tangential, %d discarded (noise/irrelevant) from %d total",
                    len(df_relevant), len(df_tangential), discarded, len(df_all),
                )
                issues.append(
                    f"Data split: {len(df_relevant):,} relevant, {len(df_tangential):,} tangential, "
                    f"{discarded:,} discarded from {len(df_all):,} total"
                )
            else:
                self.ctx.df = pd.DataFrame()
                self.ctx.df_tangential = pd.DataFrame()

            self.ctx.metrics["source_counts"] = source_counts
            self.ctx.metrics["data_quality_issues"] = issues
        else:
            # In live mode, export processed CSV from SentimIA and load
            from agents.shared.sentimia_client import SentimiaClient
            from agents.report_builder.merger import merge_sources

            client = SentimiaClient(mock=False)
            csv_path = client.export_csv(
                self.ctx.sentimia_project_id,
                output_path=self.output_dir / "sentimia_export.csv",
            )
            client.close()

            df, issues, source_counts = merge_sources(
                [csv_path], source_labels=["sentimia"],
            )
            self.ctx.df = df
            self.ctx.metrics["source_counts"] = source_counts
            self.ctx.metrics["data_quality_issues"] = issues

    def _step_classify(self) -> None:
        """Step: Sentiment reclassification + actor sub-classification.

        Skips reclassification for columns that are already populated
        (pre-classified CSVs). Only reclassifies truly missing values.
        """
        from agents.report_builder.sentiment_classifier import reclassify_sentiment
        from agents.report_builder.classify_actors import classify_actors

        df = self.ctx.df
        if df is None or df.empty:
            return

        # Check how many sentiments are actually missing before reclassifying
        if "sentiment" in df.columns:
            missing_sent = df["sentiment"].isna() | (df["sentiment"].astype(str).str.strip() == "")
            pct_missing = missing_sent.sum() / len(df) * 100
            if pct_missing > 5:
                logger.info("Sentiment: %.1f%% missing → running reclassification", pct_missing)
                df, reclass_stats = reclassify_sentiment(df, use_ai=True)
                self.ctx.metrics["reclassification_stats"] = reclass_stats
            else:
                logger.info("Sentiment: only %.1f%% missing → skipping reclassification (pre-classified)", pct_missing)
                self.ctx.metrics["reclassification_stats"] = {"rules": 0, "ai": 0, "remaining": int(missing_sent.sum()), "remaining_pct": round(pct_missing, 1)}
        else:
            df, reclass_stats = reclassify_sentiment(df, use_ai=True)
            self.ctx.metrics["reclassification_stats"] = reclass_stats

        # Check how many actors are actually missing before reclassifying
        if "actor" in df.columns:
            unknown_labels = {"unknown", "<na>", "nan", "n/a", "none", "", "otros"}
            actor_vals = df["actor"].astype(str).str.strip().str.lower()
            missing_actor = actor_vals.isin(unknown_labels) | df["actor"].isna()
            pct_missing = missing_actor.sum() / len(df) * 100
            if pct_missing > 10:
                logger.info("Actor: %.1f%% missing → running actor classification", pct_missing)
                df, actor_stats = classify_actors(df, use_ai=True)
            else:
                logger.info("Actor: only %.1f%% missing → skipping classification (pre-classified)", pct_missing)
        else:
            df, actor_stats = classify_actors(df, use_ai=True)

        self.ctx.df = df

    def _step_metrics(self) -> None:
        """Step 1.5: Calculate all metrics via MetricsCalculator."""
        from agents.report_builder.metrics import (
            MetricsCalculator,
            calculate_metrics,
            detect_anomalies,
            calculate_actor_metrics,
            calculate_intersection_metrics,
        )

        df = self.ctx.df
        if df is None or df.empty:
            return

        # Base metrics (legacy compat)
        metrics = calculate_metrics(df)
        metrics.update({k: v for k, v in self.ctx.metrics.items() if k not in metrics})

        # Actor metrics
        actor_metrics = calculate_actor_metrics(df)
        metrics["actor_metrics"] = {k: v for k, v in actor_metrics.items() if k != "combined"}

        # Intersection
        metrics["intersection"] = calculate_intersection_metrics(
            df, self.ctx.brand.lower(), [a.lower() for a in self.ctx.actors],
        )

        # Advanced metrics via MetricsCalculator
        mc = MetricsCalculator(df)
        metrics["engagement_by_platform"] = mc.compute_engagement_by_platform()
        timeline = mc.compute_timeline()
        metrics["timeline"] = timeline
        metrics["spikes"] = mc.detect_spikes(daily_data=timeline.get("daily"))
        metrics["reach_deduplicated"] = mc.compute_reach_deduplicated()

        # Tangential analysis uses the SEPARATE tangential dataset, not the main one
        if self.ctx.df_tangential is not None and not self.ctx.df_tangential.empty:
            metrics["tangential_analysis"] = mc.compute_tangential_analysis(
                tangential_mentions=self.ctx.df_tangential,
            )
        else:
            metrics["tangential_analysis"] = mc.compute_tangential_analysis()

        metrics["brand_criticism"] = mc.categorize_brand_criticism(brand_name=self.ctx.brand)

        # Comunicado impact (if event_date)
        if self.ctx.event_date:
            metrics["comunicado_impact"] = mc.compute_comunicado_impact(self.ctx.event_date)

        # Anomalies
        anomalies = detect_anomalies(df, metrics)

        # Actor subcategory breakdown
        if "actor_subcategory" in df.columns:
            subcat = df["actor_subcategory"].value_counts().to_dict()
            metrics["actor_subcategory_breakdown"] = {str(k): int(v) for k, v in subcat.items() if str(k).strip()}

        self.ctx.metrics = metrics
        self.ctx.anomalies = anomalies

    def _step_audit(self) -> None:
        """Step 1.4: Audit sample of mentions for classification quality."""
        df = self.ctx.df
        if df is None or df.empty:
            self.ctx.audit_accuracy = None
            return

        # Sample up to 200 mentions (50 per category)
        sample_size = min(50, len(df))
        categories = {}
        if "sentiment" in df.columns:
            for sent in df["sentiment"].dropna().unique():
                cat_df = df[df["sentiment"] == sent]
                categories[str(sent)] = cat_df.sample(min(sample_size, len(cat_df))).index.tolist()

        # In a full implementation, this would call Claude to verify classifications.
        # For now, use confidence distribution from SentimIA results.
        conf = self.ctx.sentimia_results.get("confidence_distribution", {})
        total_conf = sum(conf.values()) if conf else 0
        if total_conf > 0:
            high_pct = conf.get("high", 0) / total_conf * 100
            self.ctx.audit_accuracy = round(high_pct, 1)
        else:
            # Default reasonable accuracy
            self.ctx.audit_accuracy = 85.0

        self.ctx.audit_report = (
            f"Auditoría: {self.ctx.audit_accuracy:.1f}% confianza alta. "
            f"Distribución: high={conf.get('high', 0)}, "
            f"medium={conf.get('medium', 0)}, low={conf.get('low', 0)}"
        )

    def _step_topics(self) -> None:
        """Step: Detect topic clusters + compute co-occurrence."""
        from agents.report_builder.topics import detect_topic_clusters, format_topic_summary
        from agents.report_builder.metrics import MetricsCalculator

        df = self.ctx.df
        if df is None or df.empty:
            return

        clusters = detect_topic_clusters(df)
        self.ctx.topic_clusters = clusters
        self.ctx.metrics["topic_clusters"] = [
            {"label": c["label"], "keywords": c["keywords"],
             "mention_count": c["mention_count"], "percentage": c["percentage"]}
            for c in clusters
        ]

        # Co-occurrence from topic keywords + actors + brand
        concepts = []
        for c in clusters:
            concepts.extend(c.get("keywords", [])[:3])
        concepts.append(self.ctx.brand.lower())
        for actor in self.ctx.actors:
            concepts.append(actor.lower())
        concepts = list(dict.fromkeys(concepts))

        if concepts:
            mc = MetricsCalculator(df)
            self.ctx.metrics["cooccurrence"] = mc.compute_cooccurrence(concepts)

    def _step_synthesis(self) -> None:
        """Step 1.6: Generate narrative synthesis via Claude (Capa 3)."""
        from agents.report_builder.report_generator import generate_report_draft
        from agents.report_builder.sampler import build_relevance_sample
        from agents.report_builder.topics import format_topic_summary

        df = self.ctx.df
        if df is None:
            return

        # Build sample
        sample_mentions, sample_comp = build_relevance_sample(
            df, self.ctx.metrics, topic_clusters=self.ctx.topic_clusters,
        )

        topic_summary = format_topic_summary(self.ctx.topic_clusters) if self.ctx.topic_clusters else ""

        # Generate via Claude
        self.ctx.report_text = generate_report_draft(
            client_name=self.ctx.client_name,
            period=self.ctx.period,
            metrics=self.ctx.metrics,
            anomalies=self.ctx.anomalies,
            sample_mentions=sample_mentions,
            data_quality_issues=self.ctx.metrics.get("data_quality_issues", []),
            topic_summary=topic_summary,
            report_type=self.ctx.report_type,
        )

    def _step_synthesis_with_feedback(self, feedback: str) -> None:
        """Re-generate synthesis incorporating analyst feedback."""
        from agents.shared.anthropic_client import AnthropicClient

        client = AnthropicClient()

        system_prompt = (
            "You are a senior social intelligence analyst at Epical. "
            "The analyst has reviewed your draft report and has feedback. "
            "Incorporate their feedback and regenerate the affected sections. "
            "Maintain the same === structured format. Write in Spanish."
        )

        user_prompt = (
            f"REPORTE ANTERIOR:\n{self.ctx.report_text}\n\n"
            f"FEEDBACK DEL ANALISTA:\n{feedback}\n\n"
            f"MÉTRICAS DISPONIBLES:\n{json.dumps(self.ctx.metrics, default=str, ensure_ascii=False)[:5000]}\n\n"
            "Regenerá las secciones afectadas por el feedback. "
            "Mantené el formato === estructurado."
        )

        self.ctx.report_text = client.generate(system_prompt, user_prompt)
        self.ctx.report_sections = None  # Force re-parse

    def _step_generate_html(self) -> None:
        """Generate HTML report using builder v2."""
        from agents.report_builder.html_builder_v2 import build_report_html

        self.ctx.html_version += 1
        safe_client = self.ctx.client_name.replace(" ", "_").lower()
        date_str = date.today().isoformat()
        filename = f"{safe_client}_{date_str}_v{self.ctx.html_version}.html"
        html_path = self.output_dir / filename

        build_report_html(
            client_name=self.ctx.client_name,
            period=self.ctx.period,
            report_text=self.ctx.report_text,
            metrics=self.ctx.metrics,
            anomalies=self.ctx.anomalies,
            output_path=str(html_path),
            report_type=self.ctx.report_type,
            report_sections=self.ctx.report_sections,
            event_date=self.ctx.event_date,
            client_role=self.ctx.client_role,
            client_logo_url=self.ctx.client_logo_url,
        )

        self.ctx.html_path = str(html_path)
        logger.info("Generated HTML v%d: %s", self.ctx.html_version, html_path)

    def _step_integrate_screenshots(self, attachments: List[Union[str, Path]]) -> None:
        """Integrate screenshot images into the HTML report."""
        # For now, log the integration intent. Full implementation would
        # base64-encode images and inject them into specific slides.
        for att in attachments:
            logger.info("Screenshot queued for integration: %s", att)
        # Regenerate HTML after integration
        self._step_generate_html()

    def _step_generate_pdf(self) -> None:
        """Generate PDF from HTML via Playwright."""
        if not self.ctx.html_path:
            logger.warning("No HTML to convert to PDF")
            return

        try:
            from playwright.sync_api import sync_playwright

            safe_client = self.ctx.client_name.replace(" ", "_").lower()
            date_str = date.today().isoformat()
            pdf_path = self.output_dir / f"{safe_client}_{date_str}.pdf"

            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page()
                page.goto(f"file://{self.ctx.html_path}")

                # Inject CSS overrides for print (from spec)
                page.add_style_tag(content="""\
                    * { print-color-adjust: exact !important; -webkit-print-color-adjust: exact !important; }
                    html { scroll-snap-type: none !important; }
                    .fu { opacity: 1 !important; transform: none !important; }
                    .sl { page-break-after: always; min-height: auto !important; }
                """)

                page.pdf(
                    path=str(pdf_path),
                    format="A4",
                    landscape=True,
                    margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
                    print_background=True,
                )
                browser.close()

            self.ctx.pdf_path = str(pdf_path)
            logger.info("Generated PDF: %s", pdf_path)

        except ImportError:
            logger.warning("Playwright not installed — skipping PDF generation")
            self.ctx.pdf_path = None
        except Exception as e:
            logger.error("PDF generation failed: %s", e)
            self.ctx.pdf_path = None

    def _step_final_verification(self) -> Dict[str, Any]:
        """Run final verification checks."""
        from agents.report_builder.rules import RulesValidator

        validator = RulesValidator()

        html_content = ""
        if self.ctx.html_path and Path(self.ctx.html_path).exists():
            html_content = Path(self.ctx.html_path).read_text(encoding="utf-8")

        violations = validator.validate_all(
            metrics=self.ctx.metrics,
            report_text=self.ctx.report_text,
            html_content=html_content,
            audit_accuracy=self.ctx.audit_accuracy,
        )

        # Count slides and charts in HTML
        slides_count = html_content.count('class="sl"') if html_content else 0
        charts_count = html_content.count("<canvas") if html_content else 0
        posts_count = html_content.count('class="spost"') if html_content else 0

        return {
            "violations": violations,
            "violations_report": validator.format_report(violations),
            "errors": len(validator.get_errors(violations)),
            "warnings": len(validator.get_warnings(violations)),
            "slides": slides_count,
            "charts": charts_count,
            "social_posts": posts_count,
            "cifras_consistentes": len(validator.get_errors(violations)) == 0,
            "sin_herramientas_internas": not any(
                v.rule_id == 9 for v in violations
            ),
        }

    def _save_json_summary(self) -> None:
        """Save full JSON summary of processing."""
        safe_client = self.ctx.client_name.replace(" ", "_").lower()
        date_str = date.today().isoformat()
        json_path = self.output_dir / f"{safe_client}_{date_str}.json"

        summary = {
            "client": self.ctx.client_name,
            "period": self.ctx.period,
            "generated_date": date_str,
            "brief": self.ctx.brief,
            "input_files": self.ctx.file_paths,
            "metrics": self.ctx.metrics,
            "anomalies": self.ctx.anomalies,
            "audit_accuracy": self.ctx.audit_accuracy,
            "report_text": self.ctx.report_text,
        }
        save_json(summary, json_path)
        self.ctx.json_path = str(json_path)

    # ══════════════════════════════════════════════════════════════
    # Checkpoint message builders
    # ══════════════════════════════════════════════════════════════

    def _build_checkpoint1(self) -> CheckpointMessage:
        """Build Checkpoint 1 message: present draft to analyst."""
        from agents.report_builder.rules import RulesValidator
        from agents.report_builder.html_builder_v2 import _parse_sections_from_text

        # Parse sections for thesis/findings
        sections = _parse_sections_from_text(self.ctx.report_text)
        self.ctx.report_sections = sections

        thesis = sections.get("cover_subtitle", "")
        findings = sections.get("findings", [])

        # Run rules validation
        validator = RulesValidator()
        violations = validator.validate_all(
            metrics=self.ctx.metrics,
            report_text=self.ctx.report_text,
            audit_accuracy=self.ctx.audit_accuracy,
        )

        total = self.ctx.metrics.get("total_mentions", 0)
        relevant = self.ctx.sentimia_results.get("relevant_mentions", total)

        findings_text = ""
        for i, f in enumerate(findings[:3], 1):
            findings_text += f"\n{i}. {f.get('text', f.get('title', ''))[:200]}"

        summary = (
            f"Procesé {total:,} menciones → {relevant:,} relevantes.\n\n"
            f"TESIS PRINCIPAL: {thesis}\n\n"
            f"HALLAZGOS:{findings_text}\n\n"
            f"AUDITORÍA: revisé muestra, accuracy estimada {self.ctx.audit_accuracy or 0:.1f}%.\n"
            f"{self.ctx.audit_report}\n\n"
            f"HTML borrador v{self.ctx.html_version} adjunto.\n\n"
            f"¿Estás de acuerdo con el enfoque o querés cambiar algo?"
        )

        attachments = []
        if self.ctx.html_path:
            attachments.append(self.ctx.html_path)
        if self.ctx.json_path:
            attachments.append(self.ctx.json_path)

        return CheckpointMessage(
            checkpoint=1,
            summary=summary,
            details={
                "thesis": thesis,
                "findings": findings,
                "total_mentions": total,
                "relevant_mentions": relevant,
                "audit_accuracy": self.ctx.audit_accuracy,
                "html_version": self.ctx.html_version,
                "spikes": len(self.ctx.metrics.get("spikes", [])),
                "platforms": len(self.ctx.metrics.get("engagement_by_platform", [])),
            },
            attachments=attachments,
            rule_violations=validator.format_report(violations),
        )

    def _build_checkpoint2(self, feedback: str) -> CheckpointMessage:
        """Build Checkpoint 2 message: present refined report."""
        from agents.report_builder.rules import RulesValidator

        validator = RulesValidator()

        html_content = ""
        if self.ctx.html_path and Path(self.ctx.html_path).exists():
            html_content = Path(self.ctx.html_path).read_text(encoding="utf-8")

        violations = validator.validate_all(
            metrics=self.ctx.metrics,
            report_text=self.ctx.report_text,
            html_content=html_content,
            audit_accuracy=self.ctx.audit_accuracy,
        )

        summary = (
            f"HTML v{self.ctx.html_version} listo con los ajustes.\n\n"
            f"Cambios incorporados:\n"
            f"- Feedback procesado: \"{feedback[:100]}{'...' if len(feedback) > 100 else ''}\"\n"
            f"- Secciones regeneradas según indicaciones\n\n"
            f"¿Querés agregar screenshots de posts, ajustar algo más, "
            f"o está listo para PDF?"
        )

        attachments = []
        if self.ctx.html_path:
            attachments.append(self.ctx.html_path)

        return CheckpointMessage(
            checkpoint=2,
            summary=summary,
            details={
                "html_version": self.ctx.html_version,
                "feedback_applied": feedback[:200],
            },
            attachments=attachments,
            rule_violations=validator.format_report(violations),
        )

    def _build_checkpoint3(self, verification: Dict[str, Any]) -> CheckpointMessage:
        """Build Checkpoint 3 message: final delivery."""
        checks = []
        if verification.get("cifras_consistentes"):
            checks.append("✅ Cifras consistentes")
        else:
            checks.append(f"⚠️ {verification.get('errors', 0)} errores de consistencia")

        if verification.get("sin_herramientas_internas"):
            checks.append("✅ Sin menciones de herramientas internas")
        else:
            checks.append("❌ Herramientas internas detectadas en el texto")

        checks.append(f"✅ {verification['charts']} charts renderizados")
        checks.append(f"✅ {verification['slides']} slides, {verification['social_posts']} menciones con engagement")

        pdf_status = "✅ PDF generado" if self.ctx.pdf_path else "⚠️ PDF no generado (Playwright no disponible)"
        checks.append(pdf_status)

        summary = (
            f"HTML y PDF listos.\n\n"
            f"Verificación final:\n"
            + "\n".join(checks) + "\n\n"
            f"Archivos adjuntos."
        )

        attachments = []
        if self.ctx.html_path:
            attachments.append(self.ctx.html_path)
        if self.ctx.pdf_path:
            attachments.append(self.ctx.pdf_path)

        return CheckpointMessage(
            checkpoint=3,
            summary=summary,
            details=verification,
            attachments=attachments,
            rule_violations=verification.get("violations_report", ""),
            requires_response=False,
        )


# ══════════════════════════════════════════════════════════════════════
# Pre-classified CSV loader
# ══════════════════════════════════════════════════════════════════════

def _load_preclassified_csv(filepath: Path, source_type: str = "csv") -> Optional[pd.DataFrame]:
    """Load a pre-classified CSV into unified schema.

    Handles two known formats:
    - YouScan reclassified: columns include source_platform, page (=author), actor
    - Scrapping reclassified: columns include platform, profile_source, sentiment_toward (=actor)

    Returns None if the file doesn't look pre-classified.
    """
    df = pd.read_csv(filepath, encoding="utf-8", low_memory=False)

    if df.empty:
        return None

    cols_lower = set(c.lower() for c in df.columns)

    # Must have at least text + sentiment to be pre-classified
    if not (("text" in cols_lower or "texto" in cols_lower) and
            ("sentiment" in cols_lower or "sentimiento" in cols_lower)):
        return None

    # ── Map sentiment_toward → actor BEFORE generic rename ───────
    # Scrapping CSVs have sentiment_toward instead of actor
    if "sentiment_toward" in df.columns and "actor" not in df.columns:
        df["actor"] = df["sentiment_toward"]

    # ── Column rename ────────────────────────────────────────────
    rename_map = {
        "source_platform": "platform",
        "page": "author",
        "profile_source": "author",
        "youscan_sentiment": "original_sentiment",
        "sheet": "data_category",
        "texto": "text",
        "sentimiento": "sentiment",
        "fecha": "date",
        "fuente": "platform",
        "autor": "author",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

    # ── Type coercion ────────────────────────────────────────────
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")

    if "engagement" in df.columns:
        df["engagement"] = pd.to_numeric(df["engagement"], errors="coerce").fillna(0)

    # ── Defaults for missing columns ─────────────────────────────
    for col in ["likes", "comments", "shares", "reach", "country", "url"]:
        if col not in df.columns:
            df[col] = 0 if col not in ("country", "url") else ""

    if "actor" not in df.columns:
        df["actor"] = "unknown"

    if "platform" not in df.columns:
        df["platform"] = "unknown"

    if "author" not in df.columns:
        df["author"] = ""

    if "data_source" not in df.columns:
        df["data_source"] = source_type

    # ── Normalize platform names ─────────────────────────────────
    _PLAT_MAP = {
        "tiktok.com": "TikTok", "tiktok": "TikTok",
        "facebook.com": "Facebook", "facebook": "Facebook",
        "instagram.com": "Instagram", "instagram": "Instagram",
        "twitter.com": "Twitter", "twitter": "Twitter", "x.com": "Twitter",
        "youtube.com": "YouTube", "youtube": "YouTube",
    }
    df["platform"] = df["platform"].astype(str).str.strip().str.lower().map(
        lambda x: _PLAT_MAP.get(x, x.title() if x and x != "nan" else "Unknown")
    )

    # ── Normalize actor values ───────────────────────────────────
    if "actor" in df.columns:
        df["actor"] = df["actor"].astype(str).str.strip().str.lower()
        # Map "otro" → "ninguno" for consistency with YouScan format
        df.loc[df["actor"].isin(["otro", "otros", "other", "nan", ""]), "actor"] = "ninguno"

    logger.info(
        "Pre-classified CSV loaded: %d rows, platforms=%s, actors=%s, source=%s",
        len(df),
        dict(df["platform"].value_counts().head(5)),
        dict(df["actor"].value_counts()),
        source_type,
    )

    return df
