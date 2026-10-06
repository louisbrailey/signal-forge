"""Options paper automation is OFF by default — every switch, on a fresh install.

Three independent switches gate the SIMULATED options paper book, and each must
read OFF with nothing configured:

* ``research.options.paper_eod_enabled`` — the scheduled EOD chain (marks,
  reconciliation, expiry, auto-simulation step). Config default False.
* ``auto_simulate_options_enabled`` — the SECOND auto-simulation setting, a
  settings-store key SEPARATE from the equity ``auto_simulate_qualified_signals``.
  Absent reads False.
* ``auto_simulate_options_max_per_day`` — the SECOND daily cap. Absent reads 0.

And the chain is absent from the scheduler's default job table: it exists only
when the CLI injects it. Nothing here touches the live database; the settings
store is the fresh test database's.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from signalforge.config.research import OptionsConfig, ResearchConfig
from signalforge.paper.options_eod import OPTIONS_EOD_JOB
from signalforge.paper.options_ledger import (
    OPTIONS_AUTO_SIM_CAP_KEY,
    OPTIONS_AUTO_SIM_ENABLED_KEY,
    options_auto_simulate_enabled,
    options_auto_simulate_max_per_day,
)
from signalforge.scheduler import default_job_specs
from signalforge.settings_store import effective_research_config

pytestmark = pytest.mark.safety


def test_the_eod_chain_flag_defaults_off() -> None:
    assert OptionsConfig().paper_eod_enabled is False
    assert ResearchConfig().options.paper_eod_enabled is False
    assert OptionsConfig.model_fields["paper_eod_enabled"].default is False


def test_a_fresh_settings_store_leaves_every_options_switch_off(session: Session) -> None:
    assert effective_research_config(session).options.paper_eod_enabled is False
    assert options_auto_simulate_enabled(session) is False
    assert options_auto_simulate_max_per_day(session) == 0


def test_the_options_switches_are_separate_keys_from_the_equity_pair() -> None:
    assert OPTIONS_AUTO_SIM_ENABLED_KEY == "auto_simulate_options_enabled"
    assert OPTIONS_AUTO_SIM_CAP_KEY == "auto_simulate_options_max_per_day"
    assert OPTIONS_AUTO_SIM_ENABLED_KEY != "auto_simulate_qualified_signals"
    assert OPTIONS_AUTO_SIM_CAP_KEY != "auto_simulate_max_per_day"


def test_the_options_eod_chain_is_not_a_default_scheduler_job() -> None:
    assert OPTIONS_EOD_JOB not in {spec.name for spec in default_job_specs()}
