"""Local, rebuildable analytics. This package never starts benchmark trials."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULTS = ROOT / "results"
DEFAULT_DATABASE = ROOT / "analytics.duckdb"
DEFAULT_REPORTS = ROOT / "reports"
