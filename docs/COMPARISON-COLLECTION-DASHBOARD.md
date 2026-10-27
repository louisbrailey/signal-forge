# Comparison collection status

The authenticated `/kronos` page shows automatic collection status for the short
and medium books. It refreshes every 60 seconds. Set
`KRONOS_COMPARISON_STATUS_PATH` to the collector's private `status.json` path.
The application reads at most 256 KiB and displays only known states and validated
UTC timestamps. Missing, malformed, future-dated or overdue metadata is visibly
unavailable or stale. The page never opens book databases or displays interim
performance. Last-success metadata survives the collector's 64-transition
retention ring. Existing transition history seeds that summary automatically;
if no success has been recorded, the page explicitly says so.

Collection is prospective paper research. A successful collection does not
establish forecasting skill or profitability. Keep study rules and manifests
frozen until the registered evaluation endpoint. Additional historical backtests
must use separate experiments and recorded chronological boundaries; they must
not inspect or tune against this study's interim outcomes.

Release acceptance: test metadata validation, missing/stale/blocked states,
authenticated page rendering and secret-field exclusion; verify the deployed
panel matches the persisted collector timestamps. Existing research validation
gates still control strategy approval. This panel does not complete or approve
the wider strategy research program.
