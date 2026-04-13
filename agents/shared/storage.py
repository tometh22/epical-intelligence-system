"""Local JSON storage utilities for Epical Intelligence System."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

BASE_DIR = Path(os.getenv("EPICAL_BASE_DIR", Path(__file__).resolve().parent.parent.parent))


def save_json(data: Dict[str, Any], filepath: Path) -> Path:
    """Save a dictionary to a JSON file.

    Args:
        data: Dictionary to serialize.
        filepath: Destination path (absolute or relative to BASE_DIR).

    Returns:
        The absolute path of the saved file.
    """
    filepath = Path(filepath)
    if not filepath.is_absolute():
        filepath = BASE_DIR / filepath

    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    return filepath


def load_json(filepath: Path) -> Optional[Dict[str, Any]]:
    """Load a JSON file and return its contents as a dict.

    Args:
        filepath: Path to the JSON file (absolute or relative to BASE_DIR).

    Returns:
        Parsed dictionary, or None if the file does not exist or is invalid.
    """
    filepath = Path(filepath)
    if not filepath.is_absolute():
        filepath = BASE_DIR / filepath

    if not filepath.exists():
        return None
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def save_run_status(
    agent_name: str,
    status: str,
    details: Optional[Dict[str, Any]] = None,
) -> Path:
    """Save the latest run status for an agent.

    Args:
        agent_name: Name of the agent.
        status: One of 'idle', 'running', 'completed', 'error'.
        details: Optional extra information about the run.

    Returns:
        Path to the saved status file.
    """
    filepath = BASE_DIR / "outputs" / agent_name / "latest_run.json"
    data = {
        "agent": agent_name,
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "details": details or {},
    }
    return save_json(data, filepath)
