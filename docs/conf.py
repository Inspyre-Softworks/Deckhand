"""Sphinx configuration; package metadata is the version source."""
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[1]
metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
project = "Deckhand"
author = "Inspyre Softworks"
copyright = "2026, Taylor B."
release = metadata["version"]
extensions = ["myst_parser"]
source_suffix = {".md": "markdown", ".rst": "restructuredtext"}
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]
html_theme = "sphinx_rtd_theme"
