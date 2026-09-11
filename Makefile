# Signal Forge — developer workflow.
# Everything runs through `uv`; no global installs required.

UV ?= uv
RUN := $(UV) run

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
.PHONY: install
install: ## Create venv + install runtime, dev group, and the optional LLM extra
	$(UV) sync --extra llm

.PHONY: install-min
install-min: ## Runtime + dev group only (no LLM extra)
	$(UV) sync

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
.PHONY: dev
dev: ## Run API + in-process scheduler with reload
	$(RUN) uvicorn signalforge.app.main:app --host 127.0.0.1 --port 8787 --reload

.PHONY: seed
seed: ## Load clearly-labelled SIMULATED demo data
	$(RUN) signalforge seed

.PHONY: migrate
migrate: ## Alembic upgrade head
	$(RUN) alembic upgrade head

.PHONY: downgrade
downgrade: ## Alembic downgrade -1
	$(RUN) alembic downgrade -1

.PHONY: backup
backup: ## Snapshot the SQLite DB (optionally gpg-encrypted, prompts for passphrase)
	$(RUN) signalforge backup

.PHONY: killswitch-on
killswitch-on: ## Engage the emergency kill switch
	$(RUN) signalforge killswitch on --reason "manual (make)"

.PHONY: killswitch-off
killswitch-off: ## Release the emergency kill switch
	$(RUN) signalforge killswitch off --reason "manual (make)"

# ---------------------------------------------------------------------------
# Quality gates
# ---------------------------------------------------------------------------
.PHONY: fmt
fmt: ## Autofix: ruff --fix + black
	$(RUN) ruff check --fix src tests
	$(RUN) black src tests

.PHONY: lint
lint: ## Ruff + Black --check + mypy + import-linter
	$(RUN) ruff check src tests
	$(RUN) black --check src tests
	$(RUN) mypy
	$(RUN) lint-imports

.PHONY: test
test: ## Full test suite with coverage
	$(RUN) pytest

.PHONY: safety
safety: ## Only the S1-S10 invariant tests
	$(RUN) pytest -m safety

.PHONY: secrets
secrets: ## Fail on any secret not already audited into .secrets.baseline (check-only; never rewrites the baseline)
	git ls-files -z | xargs -0 $(RUN) detect-secrets-hook --baseline .secrets.baseline --exclude-files 'docs/research/.*'

.PHONY: secrets-baseline
secrets-baseline: ## Re-generate .secrets.baseline (then audit every new entry: uv run detect-secrets audit .secrets.baseline)
	$(RUN) detect-secrets scan --baseline .secrets.baseline --exclude-lines '^(revision|down_revision): str( \| None)? = "[0-9a-f]{12}"$$'

.PHONY: check
check: lint test ## Everything CI runs

.PHONY: worker
worker: ## Run the scheduler worker in the foreground (heartbeat + catch-up; Ctrl-C to stop)
	$(RUN) python -m signalforge.cli run-scheduler

.PHONY: api
api: ## Run the dashboard API in the foreground on 127.0.0.1:8787
	$(RUN) uvicorn signalforge.app.main:app --host 127.0.0.1 --port 8787

.PHONY: launchd-check
launchd-check: ## Validate the launchd plists (does NOT install them)
	plutil -lint deploy/launchd/com.signalforge.api.plist deploy/launchd/com.signalforge.worker.plist
