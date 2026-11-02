# Operator broker access

The `signalforge broker` commands are separate from automated strategy execution.
Production access defaults off. Credential references name an environment variable
or Keychain item; action files must never contain credentials.

## Inspect and verify

`signalforge broker capabilities` reports implemented scope without contacting a
provider. `signalforge broker schema` prints the exact action schema. Neither
command proves account entitlement.

After provisioning credentials yourself, use `broker` options `--provider`,
`--account`, `--key-ref` and `--secret-ref`. References have the form `env:NAME` or
`keychain:ITEM`; Webull also requires `--token-ref`. Enable only production reads
with `--allow-production-reads`, then run `audit` to check expected account identity
and provider permission metadata. `read RESOURCE` retrieves a supported resource;
incomplete snapshots fail explicitly.

## Review and submit

Create an action JSON from the schema with exact decimal strings and a review
expiry within ten minutes. `broker review PATH` saves immutable terms and returns
a single-use confirmation. `broker status ACTION_ID` shows terms and durable state.
Changing terms requires a new review.

Submission requires a trusted interactive local terminal, the saved confirmation,
production read/action flags and a fresh provider check. Transfers also require
the production transfer flag. No `--yes` or piped confirmation is provided. These
instructions do not authorize any particular transaction.

Strict provider fee caps are the default. Where the provider cannot enforce them,
the action refuses. An explicitly supported estimated-fee policy must be selected
in the review and states that actual fees and debit may exceed the checks performed
before submission. Do not mistake an estimate ceiling for a guaranteed debit cap.

## Resolve outcomes

An order acknowledgement is not settlement. Use `broker reconcile ACTION_ID` for
authoritative order resolution. A documented synchronous Coinbase internal move
can complete from a matching successful response to the exact saved request.
An uncertain response retains the account reservation;
do not resend the action or delete its database to clear it. Both apps share
`~/Library/Application Support/BrokerAccess/admission.sqlite3`, including source
and destination reservations for transfers. This coordinator supports one Mac;
independent installations cannot safely coordinate through separate databases.
Uncertain internal moves have no automatic lookup-based resolution or retry.
Both deployed apps must be upgraded before relying on cross-app exclusion.

## Implemented products

Coinbase supports scoped account/portfolio reads, orders/fills, product reads,
spot LIMIT/GTD orders, exact tracked-order cancellation and internal portfolio
moves. Webull supports account/balance/position/order reads, equity LIMIT/DAY
orders and exact tracked-order cancellation. Order submission uses the explicitly
selected estimated-fee policy described above when hard provider caps are absent.
Fee settlement and overruns are recorded during reconciliation.

External withdrawals, bank funding, Webull retail transfers, derivatives, shorting,
order replacement and streaming are not implemented. Provider entitlement and
application implementation are separate requirements; broader credentials alone
do not enable these products.

Production verification remains pending until credentials are provisioned and
account reads succeed. Fixture tests do not establish provider-granted access.
The positive Coinbase sandbox proof remains pending at the operator's request.
