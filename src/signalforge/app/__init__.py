"""FastAPI application: routers, local auth, templates, health + kill-switch API.

Phase 1 UI is server-rendered Jinja2 + HTMX + Tailwind (see ADR 0001). The
REST/SSE contract is kept stable so a Phase 2 React SPA can replace the view
layer without backend changes.
"""

from __future__ import annotations
