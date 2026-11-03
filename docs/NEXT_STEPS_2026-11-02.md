# Release priorities — November 2, 2026

## Review of Claude’s current working branch

The `claude/apple-restyle` branch contains a dashboard restyle, manual Coinbase/Webull CSV support, opt-in test isolation, an intraday datetime fold-filter correction, a paper open-risk ceiling increase, and a pre-registered 500-symbol development run. These observations come from source and commit history, not a fresh full runtime validation.

The full-pipeline and hourly-crypto reports are uncommitted work in the operating checkout. The full-pipeline report still lists the intraday result as pending. Its strategy verdicts are author-reported evidence, not independently reproduced in this review. Do not publish these as completed or imply verified profitability.

## Ordered next steps

1. Finish the outstanding intraday evaluation on its scratch copy and reconcile every reported result with its run identifiers and data snapshot. Preserve all existing frozen study rules and outcomes.
2. Review the paper open-risk ceiling increase separately from visual changes. Document the before/after portfolio loss exposure and keep real-money activation a separate decision.
3. Rebase or merge the dashboard branch with current main in an isolated checkout, resolve documentation conflicts, and run the full CI gate before deployment. Preserve the existing running checkout and its unfinished files.
4. Observe the next real post-close ingest, approved scan, and both comparison collections. A running collector alone is insufficient. Keep the Mac awake; closed-lid sleep can still miss the window.
5. Complete broker provisioning and sandbox failure drills against the current implementation. A merged broker-access PR does not demonstrate a connected, funded, tested live deployment.
6. Register the new prospective study in its own directory and protocol before collecting outcomes. Do not retrofit the frozen Kronos study or tune against its interim results.

## Repository presentation

The README uses an original vector mark, a quiet monochrome palette, one blue accent, and a source-based flow diagram. The banner is schematic and contains no invented prices or performance. Add desktop/mobile screenshots only after verifying the deployed UI and removing private account information. Motion should explain an actual workflow; decorative GIFs are intentionally omitted.
