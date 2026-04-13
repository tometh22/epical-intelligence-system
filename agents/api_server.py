"""Main FastAPI server for the Epical Intelligence System agents."""

import sys
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from agents.report_builder.api import router as report_builder_router

LOGS_DIR = PROJECT_ROOT / "logs"

app = FastAPI(
    title="Epical Intelligence System",
    description="API server for Epical Intelligence System agents",
    version="1.0.0",
)

# CORS middleware for localhost development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount agent routers
app.include_router(report_builder_router)


@app.get("/health")
async def health_check() -> dict:
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "epical-intelligence-system",
        "version": "1.0.0",
    }


@app.get("/api/logs/{agent_name}")
async def get_agent_logs(agent_name: str, lines: int = 200) -> dict:
    """Return the last N lines of an agent's log file."""
    allowed = {"report-builder", "prospecting", "content-authority", "monitor"}
    if agent_name not in allowed:
        raise HTTPException(status_code=404, detail=f"Unknown agent: {agent_name}")

    log_file = LOGS_DIR / f"{agent_name}.log"
    if not log_file.exists():
        return {"agent": agent_name, "logs": "No logs yet."}

    try:
        all_lines = log_file.read_text(encoding="utf-8").splitlines()
        return {"agent": agent_name, "logs": "\n".join(all_lines[-lines:])}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read logs: {e}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
