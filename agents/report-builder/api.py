"""FastAPI endpoints for the Report Builder agent."""

from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from agents.shared.logger import get_logger
from agents.shared.storage import load_json, save_run_status
from agents.report_builder.config import BASE_DIR
from agents.report_builder.main import run_report_builder

logger = get_logger("report-builder")

AGENT_NAME = "report-builder"
OUTPUT_DIR = BASE_DIR / "outputs" / AGENT_NAME
INPUT_DIR = BASE_DIR / "inputs"


def _run_agent_task(input_paths: List[str], source_labels: List[str], client_name: str, period: str, logo_path: str = None, theme: str = "dark", brand_color: str = "#FF1B6B", report_type: str = "crisis") -> None:
    """Background task that runs the report builder pipeline."""
    try:
        run_report_builder(
            input_files=input_paths,
            client_name=client_name,
            period=period,
            source_labels=source_labels if source_labels else None,
            logo_path=logo_path,
            theme=theme,
            brand_color=brand_color,
            report_type=report_type,
        )
    except Exception as e:
        logger.error("Background agent task failed: %s", e, exc_info=True)
        save_run_status(AGENT_NAME, "error", {"error": str(e)})


async def _save_upload(upload: UploadFile) -> Path:
    """Save an uploaded file to the inputs directory and return the path."""
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    dest = INPUT_DIR / upload.filename
    contents = await upload.read()
    with open(dest, "wb") as f:
        f.write(contents)
    logger.info("Uploaded file saved to %s (%d bytes)", dest, len(contents))
    return dest


router = APIRouter(prefix="/api/agents/report-builder", tags=["report-builder"])


@router.post("/run")
async def trigger_run(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    client_name: str = Form(...),
    period: str = Form(...),
    file2: Optional[UploadFile] = File(None),
    logo: Optional[UploadFile] = File(None),
    theme: str = Form("dark"),
    brand_color: str = Form("#FF1B6B"),
    report_type: str = Form("crisis"),
) -> dict:
    """Accept file uploads and trigger the report builder agent.

    Args:
        file: Primary data file (YouScan export).
        client_name: Client identifier.
        period: Reporting period description.
        file2: Optional second data file (scrapping export).
        logo: Optional client logo image (PNG/SVG/JPG).

    Returns:
        Confirmation dict with status.
    """
    try:
        input_paths = []  # type: List[str]
        source_labels = []  # type: List[str]
        logo_saved = None  # type: Optional[str]

        # Save primary file
        path1 = await _save_upload(file)
        input_paths.append(str(path1))
        source_labels.append("youscan")

        # Save optional second file
        if file2 is not None and file2.filename:
            path2 = await _save_upload(file2)
            input_paths.append(str(path2))
            source_labels.append("scrapping")

        # Save optional logo
        if logo is not None and logo.filename:
            logo_dest = await _save_upload(logo)
            logo_saved = str(logo_dest)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save uploaded file: {e}")

    # Update status and queue background task
    save_run_status(AGENT_NAME, "running", {
        "client": client_name,
        "period": period,
        "input_files": input_paths,
    })
    background_tasks.add_task(_run_agent_task, input_paths, source_labels, client_name, period, logo_saved, theme, brand_color, report_type)

    file_count = len(input_paths)
    return {
        "status": "accepted",
        "message": f"Report builder started for '{client_name}' ({period}) with {file_count} file(s)",
        "input_files": [Path(p).name for p in input_paths],
    }


@router.get("/status")
async def get_status() -> dict:
    """Return the latest run status for the report builder agent."""
    status_data = load_json(OUTPUT_DIR / "latest_run.json")
    if status_data is None:
        return {
            "agent": AGENT_NAME,
            "status": "idle",
        }

    # Transform to dashboard-expected format
    details = status_data.get("details", {})
    response = {
        "agent": status_data.get("agent", AGENT_NAME),
        "status": status_data.get("status", "idle"),
        "started_at": status_data.get("timestamp"),
    }  # type: dict

    if status_data.get("status") == "completed":
        response["completed_at"] = status_data.get("timestamp")
        # Build output_files with download URLs
        output_files = {}
        if details.get("docx_path"):
            docx_name = Path(details["docx_path"]).name
            output_files["docx"] = f"/api/agents/report-builder/outputs/{docx_name}"
        if details.get("json_path"):
            json_name = Path(details["json_path"]).name
            output_files["json"] = f"/api/agents/report-builder/outputs/{json_name}"
        if details.get("html_path"):
            html_name = Path(details["html_path"]).name
            output_files["html"] = f"/api/agents/report-builder/outputs/{html_name}"
        if details.get("qa_file"):
            qa_name = Path(details["qa_file"]).name
            output_files["qa"] = f"/api/agents/report-builder/outputs/{qa_name}"

        source_counts = details.get("source_counts", {})
        response["result"] = {
            "output_files": output_files,
            "metrics": {
                "total_mentions": details.get("total_mentions", 0),
                "anomalies_detected": details.get("anomalies_count", 0),
            },
            "source_counts": source_counts,
            "merge_stats": {
                "youscan": source_counts.get("youscan", 0),
                "scrapping": source_counts.get("scrapping", 0),
                "total_unified": source_counts.get("total_unified", details.get("total_mentions", 0)),
                "duplicates_removed": source_counts.get("duplicates_removed", 0),
            },
            "data_quality_warnings": details.get("data_quality_issues", []),
            "qa_status": details.get("qa_status", "N/A"),
            "qa_errors": details.get("qa_errors", 0),
            "qa_warnings": details.get("qa_warnings", 0),
        }
    elif status_data.get("status") == "error":
        response["message"] = details.get("error", "Unknown error")

    return response


@router.get("/outputs")
async def list_outputs() -> dict:
    """List all output files produced by the report builder."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    files = []  # type: List[dict]
    for f in sorted(OUTPUT_DIR.iterdir()):
        if f.is_file() and f.name != "latest_run.json":
            files.append({
                "filename": f.name,
                "size_bytes": f.stat().st_size,
                "modified": f.stat().st_mtime,
            })
    return {"outputs": files}


@router.get("/outputs/{filename}")
async def download_output(filename: str) -> FileResponse:
    """Download a specific output file."""
    file_path = OUTPUT_DIR / filename

    # Prevent path traversal
    if not file_path.resolve().is_relative_to(OUTPUT_DIR.resolve()):
        raise HTTPException(status_code=403, detail="Access denied")

    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")

    media_type = "application/octet-stream"
    if filename.endswith(".json"):
        media_type = "application/json"
    elif filename.endswith(".docx"):
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif filename.endswith(".html"):
        media_type = "text/html"

    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type=media_type,
    )
