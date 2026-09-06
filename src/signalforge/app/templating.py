"""Shared Jinja2 environment for server-rendered pages."""

from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates

from signalforge import NOT_ADVICE_NOTICE, RESEARCH_ONLY_NOTICE, __version__

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals.update(
    research_only_notice=RESEARCH_ONLY_NOTICE,
    not_advice_notice=NOT_ADVICE_NOTICE,
    app_version=__version__,
)
