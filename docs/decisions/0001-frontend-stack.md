# ADR 0001 — Phase 1 frontend: server-rendered HTMX, React deferred to Phase 2

- **Status:** accepted (2026-09-06)
- **Deciders:** Louis Brailey

## Context

The target stack in the brief specifies a React + TypeScript frontend. The
development machine currently has no Node/npm toolchain. The Phase 1 dashboards
(Overview, Candidate Scanner, Candidate Detail, Strategy Lab, Journal, Settings,
Daily Briefing) are predominantly read-views with a handful of POST actions
(paper-accept/reject, add journal note, flip kill switch, edit settings).

## Decision

Phase 1 UI is server-rendered **Jinja2 + HTMX + Tailwind** (Tailwind via CDN in
dev, built stylesheet for any packaged build). Charts use a vendored copy of
`lightweight-charts`. The backend exposes a stable **REST + SSE** contract.

Phase 2 replaces the view layer with **React + TypeScript + Vite** against the
identical REST/SSE contract. The migration is scoped to `src/signalforge/app`
templates/static and a new `frontend/` package; no other package changes.

## Consequences

- **+** No Node toolchain required to reach a working evidence dashboard.
- **+** Fewer moving parts for the MVP; faster to first end-to-end demo.
- **+** API contract is exercised from day one, so the Phase 2 SPA is low-risk.
- **−** Phase 1 interactivity is limited to what HTMX partial swaps provide.
- **−** A real (but contained) view-layer rewrite happens in Phase 2.

## Alternatives considered

- **React from Phase 1:** matches the target stack immediately, no later rewrite,
  but requires installing and maintaining a Node toolchain now and enlarges the
  MVP surface before the first working screen.
- **API-first, no UI in Phase 1:** fastest to a testable engine, but the brief
  explicitly wants a dashboard in Phase 1.
