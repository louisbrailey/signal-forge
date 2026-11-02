# ADR 0006 — full broker access in TradePilot and Signal Forge

Status: proposed implementation design, 2026-11-01. Operator direction recorded;
production access is not implemented or enabled by this document.

## Context

The operator requested that Webull and Coinbase connections have "full access
to everything", explicitly choosing **TradePilot and Signal Forge**. The target
includes account data, trading and transfers available to the operator through
official provider APIs. This is a change in requested scope from the sandbox-only
Signal Forge handoff, not evidence that any key or account already has these rights.

The operator also requires: agents never write credentials into a config; unrelated
dirty files on `claude/apple-restyle` stay untouched; execution changes require a
gatekeeper ALLOW before merge. No particular trade, transfer, destination or amount
has been authorized.

## Verified starting point

| Connection | Implemented application capability | Verification boundary |
| --- | --- | --- |
| TradePilot / Webull | Account reads and separately confirmed long-stock DAY orders | Existing token was verified in the handoff; this continuation checked config environment `production` only. Live-trading switch remains disabled. |
| TradePilot / Coinbase | Read-only accounts and balances, `server/coinbase_service.py` | Both required config fields absent; verifier exits before networking. |
| Signal Forge / Webull | Sandbox equity LIMIT/DAY adapter | No sandbox key pair in the supported environment or Keychain locations; operator-bound smoke proof unavailable. |
| Signal Forge / Coinbase | Static sandbox accounts, positions and order adapter | Public GET accounts/history/portfolios and parsers exercised. Wrong-account proof refused; positive proof deliberately pending at operator direction. |
| Coinbase MCP | Separate Claude Code connection described in handoff | No Coinbase or Webull connector tool is available in this Codex session. Its OAuth grant is not an application credential. |

## Proposed design

1. Track **requested**, **provider-granted**, **implemented** and **verified**
   capabilities independently per provider, environment and account. Display all
   four states. Effective access is their intersection; a requested permission
   never becomes a success label by itself. List account restrictions and missing
   entitlements rather than treating partial visibility as a complete portfolio.
2. Support all officially available account-data permissions for the operator's
   selected accounts. Implement complete pagination and fail incomplete snapshots
   explicitly. Product and market-data entitlements remain provider decisions.
3. Introduce explicit production adapters, separately registered and pinned to
   reviewed production origins. Never repoint `*_sandbox` classes, accept an arbitrary
   base URL, follow cross-origin redirects, or weaken `is_paper()` to admit production.
   Sandbox proof stays a sandbox proof; production needs a distinct account and
   environment attestation with operator-supplied expected identity.
4. Add Coinbase trading and eligible Webull products through saved, immutable
   reviews and per-action typed confirmation. Bind exact account, environment,
   instrument, side, quantity, price, expiry and fee limits; invalidate approval
   on any change. Preserve durable idempotency and resolution of uncertain outcomes.
   No test transaction is necessary to verify account permission metadata.
5. Transfers are a separate feature, not an order-adapter method. Each review must
   bind source, destination, asset, amount, network where relevant, fees and expiry.
   Require a fresh explicit confirmation of those exact terms. Provider eligibility
   and supported API product must be established before a transfer route is exposed.
   Do not infer withdrawal or funding authority from permission to trade.
6. Preserve default-off operation, kill switches, strategy arming and deterministic
   risk decisions. AI, documents and connector messages confer no transaction
   authority. No agent submits an actual trade or transfer under this scope request.
7. The operator supplies fresh provider credentials out of band. Signal Forge
   references env/Keychain names only; TradePilot's existing private credential
   configuration is edited only by the operator. Never copy an MCP token into an
   app, reuse chat-exposed private keys, log values, or commit private state.

## Implementation and acceptance sequence

1. Finish PR #50 under ADR 0003's existing sandbox boundary and preserve its
   exact-head CI/gatekeeper evidence independently of this expansion.
2. Review this design together with D6 §§0, 12, 13, 16, 17, 18 and 22. Before a
   live implementation merges, amend the canonical D6 boundary, architecture,
   safety/import contracts and shipped promises together, with gatekeeper ALLOW.
   This proposal alone supersedes none of those safeguards.
3. Add a read-only permission/account audit for each actual API product using
   operator-provisioned keys. A wider key grant does not implement missing routes;
   successful authentication does not prove trade/transfer entitlement.
4. Build and test the production account, trading and transfer surfaces in thin
   increments. Use fake provider responses in CI. Cover account substitution,
   expired approvals, duplicate requests, uncertain responses, partial failures,
   redaction, kill switches, default-disabled operation and environment mismatch.
5. Obtain gatekeeper ALLOW and passing CI on each exact implementation diff.
   Perform read-only production verification after operator provisioning. Any
   actual transaction requires its own subsequent explicit operator instruction.

## Provider limits and sources

Webull distinguishes the retail Trading API from its institutional Broker API.
Broker API funding/transfers require the applicable partner credentials and
permissions; a working retail token does not establish those entitlements:
[API products](https://developer.webull.com/apis/docs/),
[Broker API prerequisites](https://developer.webull.com/apis/docs/broker-api/getting-started/),
[retail API application](https://developer.webull.com/apis/docs/authentication/IndividualApplicationAPI/).

Coinbase portfolio key scope can limit visibility; "full access" cannot be inferred
from one successful accounts call:
[Advanced Trade portfolios](https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/guides/portfolios).
Its unauthenticated sandbox returns static mock data, not production-account proof:
[sandbox reference](https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/sandbox).

## Consequences

The requested scope is recorded for both apps, while provider permissions,
application support and runtime evidence remain separate. Current blockers are
operator provisioning, missing production implementations and review of the
explicit boundary amendment. This document enables no production route, changes
no permission grant and authorizes no particular financial transaction.
