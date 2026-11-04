# Webull account visibility

Open **Paper trading → Webull account** (`/accounts/webull`) in the authenticated
Signal Forge dashboard. It shows actual Webull balances and returned positions,
separate from simulated funds. There are no trading controls on this page.

The official account API was verified on 2026-11-03: account discovery, balance
and position reads succeeded; one account and zero open positions were returned.
This is a dated verification, not a promise of ongoing authentication.

## Architecture and refresh

Existing private credential/token store → isolated, GET-only official SDK exporter
→ atomic owner-only normalized snapshot → authenticated, network-free dashboard.

The exporter uses the existing Webull SDK interpreter, with Signal Forge `src`
on `PYTHONPATH`. It does not need TradePilot's LAN gateway to be running. The
exporter is compatible with that SDK's existing Python 3.9 environment; the main
Signal Forge application remains Python 3.12. No packages need to be duplicated.
Verified SDK distribution: `webull-openapi-python-sdk==3.0.0`. Other versions
are refused until their request/transport behavior is reviewed. Pin the exporter
source to the reviewed commit or an immutable release directory, not a worktree
whose branch may change while the collector remains installed.

```sh
PYTHONPATH=/absolute/signal-forge/src /absolute/sdk-environment/bin/python \
  -m signalforge.execution.brokers.webull_readonly \
  --allow-account-reads \
  --private-config /absolute/existing-tradepilot-private/config.json \
  --output /absolute/signal-forge/data/webull-readonly/account.json \
  --kill-switch /absolute/signal-forge/data/kill_switch.json
```

Paths are references, never key values. Do not paste credentials into commands,
chat or `.env`. The existing private files must be owned by the operator and mode
600; the snapshot directory is mode 700. The exporter never creates or refreshes
credentials. Optional `WEBULL_READONLY_SNAPSHOT_PATH` changes only the dashboard
snapshot location, not the source of credentials.

Install the provided launchd template with absolute paths substituted. It runs
every 300 seconds, with RunAtLoad for login/reboot recovery; it is not configured
to repeatedly restart on provider errors. The Mac must be awake and logged in.
The dashboard reads every 60 seconds and marks data stale after 15 minutes. An
explicit current failure or emergency stop is visible immediately. Retained old
values remain labelled unavailable/stale, never a healthy empty account.

Account retrieval time is shown in UTC. Individual position-price timestamps and
market-data latency are not supplied by this endpoint; do not call them live.
Missing fields say “Unavailable,” not zero. Values keep their supplied currency;
no currency conversion or inferred buying power is performed. This is the API's
aggregated position list, not trade-lot, open-order or transfer accounting. Caps:
10 accounts, 500 positions per account, 1 MiB final snapshot; oversize/incomplete
responses fail instead of silently truncating. Only the latest sanitized snapshot
is retained; provider payloads are not cached. Local account data remains private.

## Troubleshooting and trading boundary

- **Unavailable:** inspect the collector's fixed error category and last-success
  timestamp. Credentials, provider error bodies and financial values never go in
  logs. Check network, file permissions and Webull session validity.
- **Authentication required:** renew through the existing operator Webull flow.
  Do not disable MFA or use unofficial APIs. The exporter never initiates MFA.
- **Paused:** the emergency stop blocks further provider reads.
- **Stale:** check `launchctl print gui/$(id -u)/com.signalforge.webull-readonly`;
  periodic jobs normally show not-running between checks. Check that the Mac is awake.
- **Trading disabled:** this is intentional. Read-only access does not prove order
  permissions or profitable strategies. Future trading needs separate explicit
  enablement, verified account permissions, the existing human review controls,
  risk checks and reconciliation tests. No autonomous trading is added here.

Uninstall only the read-only collector using `launchctl bootout` on its plist;
the regular worker and frozen research collectors are independent. Stop and remove
its private snapshot separately if account visibility is no longer wanted.

Research signal only — no order was placed.

Offline SDK transport check (synthetic credentials only; sockets forbidden):
`PYTHONPATH=src /absolute/sdk-environment/bin/python scripts/check_webull_readonly_sdk.py`.
It tests redirect refusal, GET-only calls, TLS verification, no retry, error/debug
redaction and unchanged synthetic credential files against the actual pinned SDK.
