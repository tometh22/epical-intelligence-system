"""Shared logging setup for Epical Intelligence System."""

import logging
import os
from pathlib import Path
from typing import Optional


def get_logger(agent_name: str, base_dir: Optional[Path] = None) -> logging.Logger:
    """Create and return a configured logger for the given agent.

    Writes to both console (stdout) and a log file at /logs/{agent_name}.log.

    Args:
        agent_name: Name of the agent (used for logger name and log file).
        base_dir: Project root directory. Defaults to two levels up from this file.

    Returns:
        Configured logging.Logger instance.
    """
    if base_dir is None:
        base_dir = Path(__file__).resolve().parent.parent.parent

    log_dir = base_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{agent_name}.log"

    logger = logging.getLogger(f"epical.{agent_name}")

    # Avoid adding duplicate handlers if called multiple times
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger
