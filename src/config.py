"""Configuration loader and path helpers.

Every script imports from here so paths and parameters live in exactly one
place (../config.yaml). All paths resolve relative to the project root, so the
pipeline runs identically no matter which directory you launch it from.
"""
from __future__ import annotations

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_config() -> dict:
    """Read config.yaml from the project root."""
    with open(PROJECT_ROOT / "config.yaml", "r") as fh:
        return yaml.safe_load(fh)


def path(*parts: str) -> Path:
    """Resolve a path relative to the project root."""
    return PROJECT_ROOT.joinpath(*parts)


def raw_dir(cfg: dict) -> Path:
    p = path(cfg["data_source"]["raw_dir"])
    p.mkdir(parents=True, exist_ok=True)
    return p


def processed_dir(cfg: dict) -> Path:
    p = path(cfg["data_source"]["processed_dir"])
    p.mkdir(parents=True, exist_ok=True)
    return p
