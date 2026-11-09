"""Helpers shared across test modules (not fixtures — those live in conftest.py)."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

from alembic import command
from alembic.config import Config

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
PKG_ROOT = SRC_ROOT / "signalforge"


def alembic_config(url: str) -> Config:
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PKG_ROOT / "db/migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def migrate_to_head(url: str) -> None:
    command.upgrade(alembic_config(url), "head")


def run_python(code: str) -> subprocess.CompletedProcess[str]:
    """Run ``code`` in a clean interpreter (fresh ``sys.modules``)."""
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )


def iter_source_files(*subpackages: str) -> Iterator[Path]:
    """Yield ``.py`` files under the given subpackages (or the whole package)."""
    roots = [PKG_ROOT / s for s in subpackages] if subpackages else [PKG_ROOT]
    for root in roots:
        yield from sorted(root.rglob("*.py"))


def bind_matching_oos_scope(session, run, spec, *, symbols, source="fixture", config=None):
    """Synthetic matching scope for tests whose purpose is not scope failure.
    Never use this for intentionally unknown legacy evidence fixtures."""
    from datetime import UTC, datetime

    from signalforge.db.models import StrategyPromotionEvaluation
    from signalforge.research.persistence import spec_json_hash
    from signalforge.research.promotion import get_or_create_dataset_snapshot
    from signalforge.settings_store import effective_research_config

    cfg = config or effective_research_config(session)
    snapshot = get_or_create_dataset_snapshot(session, symbols=list(symbols))
    evaluation = StrategyPromotionEvaluation(
        strategy_version_id=run.strategy_version_id,
        dataset_snapshot_id=snapshot.id,
        evaluated_at=run.created_at or datetime.now(UTC),
        config_hash=cfg.config_hash,
        spec_json_hash=spec_json_hash(spec),
        universe_json=list(symbols),
        window_start=run.date_start,
        window_end=run.date_end,
        data_provenance_json={"sources": [source]},
        passed=True,
    )
    session.add(evaluation)
    session.flush()
    run.config_hash = cfg.config_hash
    run.params_json = {
        "purpose": "development_oos",
        "dataset_snapshot": {"id": snapshot.id, "key": snapshot.key},
        "promotion_evaluation_id": evaluation.id,
        "source": source,
        "symbols": list(symbols),
        "spec_json_hash": spec_json_hash(spec),
        "reproduces_evaluation": dict.fromkeys(
            ("symbols", "window_start", "until", "source", "config_hash"), True
        ),
        **(run.params_json or {}),
    }
    session.flush()
    return snapshot
