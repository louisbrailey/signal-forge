# ADR 0007 — Webull read-only account display

Operator request, 2026-11-03: verify the existing connection and show account and
positions in Signal Forge; keep real-money trading disabled. The wish to trade
later is not activation or transaction authorization.

The network side stays inside `execution/brokers/webull_readonly.py`, launched as
an explicit standalone exporter, not imported by app, scheduler, strategies or
LLMs. It uses the already-installed official Webull SDK, not website scraping or
reverse-engineered APIs. Its transport construction checks the production host,
HTTPS, API version v3, GET method, and exactly these account resource paths:
accounts/list, assets/balances/get, assets/positions/list. SDK retries and redirects
are disabled and TLS verification enabled. No order methods are instantiated.

The exporter references the **existing operator-owned TradePilot private JSON
store and existing token file**. This narrowly extends ADR 0006's env/Keychain
reference choices for reads only. Owner-only files are required. No credentials
are copied to Signal Forge configuration, database, snapshot, browser or logs.
No login, token refresh, MFA request, credential acquisition or token write is
implemented. Expired or missing authentication fails closed until the operator
renews it through their existing Webull workflow. SDK logging is suppressed.

Only a bounded, allowlisted, masked snapshot crosses into `account_view.py` and
the authenticated dashboard. The view has no network access, no execution import,
no mutation endpoint and no account-selection-to-order handoff. These real account
values never fund the paper ledger, change risk budgets, or enter frozen studies.
Manual portfolio CSV import remains network-free. Existing S1/S2/S15 contracts
remain unchanged; focused safety tests enforce the new read-only boundary.

The explicit exporter opt-in is separate from `execution.enabled`; enabling
account reads never enables execution. It refuses a TradePilot config with live
trading enabled and checks the Signal Forge emergency stop before every request.
One independent launchd job runs every five minutes, with a single-instance lock.
No automatic polling exists without installation/explicit opt-in. Snapshot failure
retains the last good values with an unavailable state, never a fabricated zero.

Future real-money trading remains the separate human-reviewed ADR 0006 workflow;
this change does not arm it, grant entitlements, or establish strategy readiness.
Execution-related changes require gatekeeper ALLOW and passing checks before
integration/deployment. This design preserves the original frozen collectors.
