"""SentimIA API client — HTTP wrapper for the social intelligence processing backend.

Implements the 7 endpoints from the spec:
    1. create_project  → POST /api/v2/projects
    2. upload_file     → POST /api/v2/projects/{id}/upload
    3. process         → POST /api/v2/projects/{id}/process
    4. get_status      → GET  /api/v2/projects/{id}/status
    5. get_results     → GET  /api/v2/projects/{id}/results
    6. get_mentions    → GET  /api/v2/projects/{id}/mentions
    7. export_csv      → GET  /api/v2/projects/{id}/export

Supports polling with configurable intervals and a mock mode for testing
without a running SentimIA backend.

If SENTIMIA_API_URL is not set, the client defaults to mock mode.
"""

import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from dotenv import load_dotenv

from agents.shared.logger import get_logger

load_dotenv()

logger = get_logger("sentimia-client")

DEFAULT_BASE_URL = os.getenv("SENTIMIA_API_URL", "")
DEFAULT_API_KEY = os.getenv("SENTIMIA_API_KEY", "")

# Polling defaults
POLL_INTERVAL_SECONDS = 15
POLL_MAX_ATTEMPTS = 120  # 30 minutes at 15s intervals


class SentimiaError(Exception):
    """Raised when SentimIA API returns an error."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"SentimIA API error {status_code}: {detail}")


class SentimiaClient:
    """HTTP client for the SentimIA processing backend.

    Args:
        base_url: API base URL (default: SENTIMIA_API_URL env var; if unset → mock mode).
        api_key: API key for authentication (default: SENTIMIA_API_KEY env var).
        mock: If True, returns synthetic responses without making HTTP calls.
            Useful for testing and development.
    """

    def __init__(
        self,
        base_url: str = "",
        api_key: str = "",
        mock: bool = False,
        timeout: int = 60,
    ) -> None:
        resolved_url = base_url or DEFAULT_BASE_URL
        if not resolved_url and not mock:
            logger.warning(
                "SENTIMIA_API_URL not set — falling back to mock mode. "
                "Set SENTIMIA_API_URL to connect to the real backend."
            )
            mock = True

        self.base_url = resolved_url.rstrip("/") if resolved_url else ""
        self.api_key = api_key or DEFAULT_API_KEY
        self.mock = mock
        self.timeout = timeout
        self._session = None

        if self.mock:
            logger.info("SentimIA client initialized in MOCK mode")
        else:
            logger.info("SentimIA client initialized: %s", self.base_url)

    def _get_session(self):
        """Lazy-init httpx client."""
        if self._session is None:
            import httpx
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self._session = httpx.Client(
                base_url=self.base_url,
                headers=headers,
                timeout=self.timeout,
            )
        return self._session

    def _request(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        """Make an HTTP request and return parsed JSON."""
        session = self._get_session()
        response = getattr(session, method)(path, **kwargs)
        if response.status_code >= 400:
            detail = response.text[:500]
            try:
                detail = response.json().get("detail", detail)
            except Exception:
                pass
            raise SentimiaError(response.status_code, detail)
        return response.json()

    # ──────────────────────────────────────────────────────────────
    # 1. Create project
    # ──────────────────────────────────────────────────────────────

    def create_project(
        self,
        name: str,
        brand: str,
        context: str,
        actors: List[str],
        language: str = "es",
    ) -> str:
        """Create a new analysis project.

        Args:
            name: Project name (e.g. "Avianca Crisis Marzo 2026").
            brand: Primary brand being analyzed.
            context: Brief / context from the analyst.
            actors: List of secondary actors/entities.
            language: Content language (default "es").

        Returns:
            project_id: Unique project identifier.
        """
        if self.mock:
            project_id = f"mock-proj-{int(time.time())}"
            logger.info("MOCK: Created project '%s' → %s", name, project_id)
            return project_id

        data = {
            "name": name,
            "brand": brand,
            "context": context,
            "actors": actors,
            "language": language,
        }
        result = self._request("post", "/api/v2/projects", json=data)
        project_id = result["project_id"]
        logger.info("Created project '%s' → %s", name, project_id)
        return project_id

    # ──────────────────────────────────────────────────────────────
    # 2. Upload file
    # ──────────────────────────────────────────────────────────────

    def upload_file(
        self,
        project_id: str,
        file_path: Union[str, Path],
        source_type: str = "youscan",
    ) -> str:
        """Upload a data file to a project.

        Args:
            project_id: Target project ID.
            file_path: Path to CSV/Excel/zip file.
            source_type: Data source type ("youscan", "scrapping", "csv").

        Returns:
            upload_id: Unique upload identifier.
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        if self.mock:
            upload_id = f"mock-upload-{file_path.stem}"
            logger.info("MOCK: Uploaded '%s' to project %s → %s", file_path.name, project_id, upload_id)
            return upload_id

        import httpx
        with open(file_path, "rb") as f:
            files = {"file": (file_path.name, f, "application/octet-stream")}
            data = {"source_type": source_type}
            # Use a fresh request without JSON content-type for multipart
            session = self._get_session()
            response = session.post(
                f"/api/v2/projects/{project_id}/upload",
                files=files,
                data=data,
            )
        if response.status_code >= 400:
            raise SentimiaError(response.status_code, response.text[:500])
        result = response.json()
        upload_id = result["upload_id"]
        logger.info("Uploaded '%s' (%s) to project %s → %s",
                     file_path.name, source_type, project_id, upload_id)
        return upload_id

    # ──────────────────────────────────────────────────────────────
    # 3. Process (launch Capa 0 + 1 + 2)
    # ──────────────────────────────────────────────────────────────

    def process(
        self,
        project_id: str,
        options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Launch processing pipeline (Capa 0 + 1 + 2).

        Args:
            project_id: Project to process.
            options: Optional processing options (e.g. {"layers": [0, 1, 2]}).

        Returns:
            job_id: Processing job identifier.
        """
        if self.mock:
            job_id = f"mock-job-{project_id}"
            logger.info("MOCK: Launched processing for %s → %s", project_id, job_id)
            return job_id

        data = {"options": options or {"layers": [0, 1, 2]}}
        result = self._request("post", f"/api/v2/projects/{project_id}/process", json=data)
        job_id = result["job_id"]
        logger.info("Launched processing for %s → job %s", project_id, job_id)
        return job_id

    # ──────────────────────────────────────────────────────────────
    # 4. Get status
    # ──────────────────────────────────────────────────────────────

    def get_status(self, project_id: str) -> Dict[str, Any]:
        """Get project processing status.

        Returns:
            {
                "status": "pending" | "processing" | "completed" | "error",
                "progress": float (0-100),
                "current_layer": int,
                "mentions_processed": int,
                "estimated_remaining_seconds": int | None,
                "error": str | None
            }
        """
        if self.mock:
            return {
                "status": "completed",
                "progress": 100.0,
                "current_layer": 2,
                "mentions_processed": 14403,
                "estimated_remaining_seconds": None,
                "error": None,
            }

        return self._request("get", f"/api/v2/projects/{project_id}/status")

    # ──────────────────────────────────────────────────────────────
    # 5. Get results (aggregated)
    # ──────────────────────────────────────────────────────────────

    def get_results(self, project_id: str) -> Dict[str, Any]:
        """Get aggregated results from processed project.

        Returns:
            {
                "total_mentions": int,
                "relevant_mentions": int,
                "irrelevant_mentions": int,
                "tangential_mentions": int,
                "sentiment_breakdown": {...},
                "actor_breakdown": {...},
                "platform_breakdown": {...},
                "confidence_distribution": {"high": int, "medium": int, "low": int},
                "processing_stats": {...}
            }
        """
        if self.mock:
            return _mock_aggregated_results()

        return self._request("get", f"/api/v2/projects/{project_id}/results")

    # ──────────────────────────────────────────────────────────────
    # 6. Get mentions (with filters)
    # ──────────────────────────────────────────────────────────────

    def get_mentions(
        self,
        project_id: str,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """Get individual mentions with classification data.

        Args:
            project_id: Project ID.
            filters: Optional filters (e.g. {"sentiment": "negative", "actor": "brand"}).
            limit: Max mentions to return per page.
            offset: Pagination offset.

        Returns:
            {
                "mentions": [...],
                "total": int,
                "has_more": bool
            }
        """
        if self.mock:
            return _mock_mentions(filters, limit)

        params: Dict[str, Any] = {"limit": limit, "offset": offset}
        if filters:
            for k, v in filters.items():
                params[f"filter_{k}"] = v

        return self._request("get", f"/api/v2/projects/{project_id}/mentions", params=params)

    # ──────────────────────────────────────────────────────────────
    # 7. Export CSV
    # ──────────────────────────────────────────────────────────────

    def export_csv(
        self,
        project_id: str,
        output_path: Optional[Union[str, Path]] = None,
    ) -> Path:
        """Export processed data as CSV.

        Args:
            project_id: Project ID.
            output_path: Where to save the CSV. If None, uses temp dir.

        Returns:
            Path to the exported CSV file.
        """
        if output_path is None:
            import tempfile
            output_path = Path(tempfile.mkdtemp()) / f"{project_id}_export.csv"
        output_path = Path(output_path)

        if self.mock:
            # Write a minimal CSV for testing
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                "date,text,sentiment,author,platform,engagement,likes,comments,shares,reach,actor,relevance\n"
                "2026-03-30,Test mention,negativo,@user1,Twitter,100,80,10,10,50000,brand,relevant\n",
                encoding="utf-8",
            )
            logger.info("MOCK: Exported CSV to %s", output_path)
            return output_path

        session = self._get_session()
        response = session.get(f"/api/v2/projects/{project_id}/export")
        if response.status_code >= 400:
            raise SentimiaError(response.status_code, response.text[:500])

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(response.content)
        logger.info("Exported CSV to %s (%d bytes)", output_path, len(response.content))
        return output_path

    # ──────────────────────────────────────────────────────────────
    # High-level: poll until processing completes
    # ──────────────────────────────────────────────────────────────

    def wait_for_processing(
        self,
        project_id: str,
        poll_interval: int = POLL_INTERVAL_SECONDS,
        max_attempts: int = POLL_MAX_ATTEMPTS,
        on_progress: Optional[callable] = None,
    ) -> Dict[str, Any]:
        """Poll get_status until processing completes or fails.

        Args:
            project_id: Project to monitor.
            poll_interval: Seconds between polls.
            max_attempts: Max polling attempts before timeout.
            on_progress: Optional callback(status_dict) called on each poll.

        Returns:
            Final status dict.

        Raises:
            SentimiaError: If processing fails.
            TimeoutError: If max_attempts exceeded.
        """
        for attempt in range(1, max_attempts + 1):
            status = self.get_status(project_id)

            if on_progress:
                on_progress(status)

            state = status.get("status", "")

            if state == "completed":
                logger.info("Processing completed for %s after %d polls", project_id, attempt)
                return status

            if state == "error":
                error_msg = status.get("error", "Unknown processing error")
                raise SentimiaError(500, f"Processing failed: {error_msg}")

            progress = status.get("progress", 0)
            remaining = status.get("estimated_remaining_seconds")
            remaining_str = f", ~{remaining}s remaining" if remaining else ""
            logger.info(
                "Processing %s: %.0f%% (poll %d/%d%s)",
                project_id, progress, attempt, max_attempts, remaining_str,
            )

            if not self.mock:
                time.sleep(poll_interval)

        raise TimeoutError(
            f"Processing for {project_id} did not complete after {max_attempts} polls"
        )

    # ──────────────────────────────────────────────────────────────
    # High-level: full pipeline (create → upload → process → wait)
    # ──────────────────────────────────────────────────────────────

    def run_full_pipeline(
        self,
        name: str,
        brand: str,
        context: str,
        actors: List[str],
        file_paths: List[Union[str, Path]],
        source_types: Optional[List[str]] = None,
        on_progress: Optional[callable] = None,
    ) -> Dict[str, Any]:
        """Run the complete SentimIA pipeline: create → upload → process → wait → results.

        Args:
            name: Project name.
            brand: Primary brand.
            context: Analyst brief.
            actors: Secondary actors.
            file_paths: Files to upload.
            source_types: Source type per file (defaults to "csv").
            on_progress: Callback for progress updates.

        Returns:
            {
                "project_id": str,
                "results": Dict (aggregated results),
                "status": Dict (final status),
            }
        """
        # 1. Create project
        project_id = self.create_project(name, brand, context, actors)

        # 2. Upload files
        if source_types is None:
            source_types = ["csv"] * len(file_paths)

        upload_ids = []
        for file_path, src_type in zip(file_paths, source_types):
            upload_id = self.upload_file(project_id, file_path, src_type)
            upload_ids.append(upload_id)

        # 3. Launch processing
        job_id = self.process(project_id)

        # 4. Wait for completion
        final_status = self.wait_for_processing(
            project_id, on_progress=on_progress,
        )

        # 5. Get results
        results = self.get_results(project_id)

        logger.info(
            "Full pipeline completed for '%s': %d mentions processed",
            name, results.get("total_mentions", 0),
        )

        return {
            "project_id": project_id,
            "job_id": job_id,
            "upload_ids": upload_ids,
            "results": results,
            "status": final_status,
        }

    def close(self) -> None:
        """Close the HTTP session."""
        if self._session is not None:
            self._session.close()
            self._session = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


# ══════════════════════════════════════════════════════════════════════
# Mock data generators (for testing without SentimIA backend)
# ══════════════════════════════════════════════════════════════════════

def _mock_aggregated_results() -> Dict[str, Any]:
    """Return realistic mock aggregated results."""
    return {
        "total_mentions": 38172,
        "relevant_mentions": 14403,
        "irrelevant_mentions": 7337,
        "tangential_mentions": 2084,
        "sentiment_breakdown": {
            "negativo": {"count": 10208, "percentage": 70.9},
            "neutro": {"count": 2615, "percentage": 18.2},
            "positivo": {"count": 1580, "percentage": 11.0},
        },
        "actor_breakdown": {
            "cossio": 11546,
            "avianca": 702,
            "ambos": 2040,
            "otros": 115,
        },
        "platform_breakdown": {
            "Twitter": 5035,
            "Facebook": 4684,
            "TikTok": 3595,
            "Instagram": 783,
            "YouTube": 306,
        },
        "confidence_distribution": {
            "high": 11200,
            "medium": 2800,
            "low": 403,
        },
        "processing_stats": {
            "total_batches": 623,
            "errors": 0,
            "processing_time_seconds": 1847,
        },
    }


def _mock_mentions(
    filters: Optional[Dict[str, Any]] = None,
    limit: int = 100,
) -> Dict[str, Any]:
    """Return mock mentions list."""
    import random
    from datetime import datetime, timedelta

    base_date = datetime(2026, 3, 29)
    sentiments = ["negativo", "negativo", "negativo", "positivo", "neutro"]
    platforms = ["Twitter", "Facebook", "TikTok", "Instagram"]
    actors = ["cossio", "cossio", "avianca", "ambos", "otros"]
    texts = [
        "Terrible lo que hizo Cossio en el avión, irresponsable total",
        "Total apoyo a Avianca, hicieron bien en denunciar",
        "¿Justicia o exageración? Esto da para debate largo",
        "PÉSIMO servicio de Avianca, nada que ver con Cossio pero aprovecho",
        "Cossio tiene razón, Avianca exagera porque quiere plata",
        "La seguridad aérea no es un juego, bien por Avianca",
        "Ni Avianca ni Cossio, los pasajeros son los que sufren",
        "Este influencer cree que puede hacer lo que quiera sin consecuencias",
    ]

    mentions = []
    for i in range(min(limit, 200)):
        date = base_date + timedelta(days=random.randint(0, 9))
        mentions.append({
            "id": f"mock-{i}",
            "date": date.isoformat(),
            "text": random.choice(texts),
            "sentiment": random.choice(sentiments),
            "author": f"@user_{random.randint(1, 500)}",
            "platform": random.choice(platforms),
            "engagement": random.randint(5, 60000),
            "likes": random.randint(5, 50000),
            "comments": random.randint(0, 5000),
            "shares": random.randint(0, 3000),
            "reach": random.randint(1000, 500000),
            "actor": random.choice(actors),
            "relevance": random.choice(["relevant", "relevant", "relevant", "tangential"]),
            "confidence": random.choice(["high", "high", "high", "medium", "low"]),
            "direction": random.choice(["toward_brand", "toward_actor", "neutral", "general"]),
        })

    # Apply filters
    if filters:
        if "sentiment" in filters:
            mentions = [m for m in mentions if m["sentiment"] == filters["sentiment"]]
        if "actor" in filters:
            mentions = [m for m in mentions if m["actor"] == filters["actor"]]
        if "relevance" in filters:
            mentions = [m for m in mentions if m["relevance"] == filters["relevance"]]

    return {
        "mentions": mentions[:limit],
        "total": len(mentions),
        "has_more": len(mentions) > limit,
    }
