"""The execution settings are OFF by default and are excluded from the
approval-scope hash — so no live approval moved out of scope when this section
appeared.

This is the 2026-09-11 incident, in negative: adding an ``agents`` section to
``ResearchConfig`` silently changed the hash used in the five-part scope match,
live scans matched no approved scope, and it was masked only because those scans
produced zero qualified candidates. ``SCOPE_HASH_FIELDS`` was narrowed to the
signal-shaping sections to stop it happening again; ``execution`` is outside it
for the stronger reason that it decides only whether an already-gated decision
may be SUBMITTED.
"""

from __future__ import annotations

from signalforge.config.hashing import config_hash as hash_payload
from signalforge.config.research import ExecutionConfig, ResearchConfig

#: The default config's ``config_hash`` as computed on the parent commit, BEFORE
#: ``ExecutionConfig`` existed. It must not move.
CONFIG_HASH_BEFORE_EXECUTION_SECTION = (
    "7fb8213a9df09fb8ac134616ecc18f1879f15b2c5ae999b459d9ea173bef3850"  # pragma: allowlist secret
)

#: The two ``config_hash`` values recorded on the live PASSING promotion
#: evaluations. FACT, verified by a read-only ``SELECT`` against
#: ``data/signalforge.sqlite`` on 2026-09-12 while the probation worker was
#: running::
#:
#:     select distinct config_hash from strategy_promotion_evaluation
#:      where passed = 1;
#:
#: returned exactly these two rows (``11b54aee…`` on evaluations 20/23/32/35,
#: ``fe365720…`` on 43/44/45 — the current one).
LIVE_APPROVAL_CONFIG_HASHES = (
    "11b54aee64dbc265c15dbc09759efdc67a654c733b55d615e63b9d7032ce6b17",  # pragma: allowlist secret
    "fe365720c0b61717649bba1b96e20a2d5c126ee6d4359f8c658510beda7c0a54",  # pragma: allowlist secret
)

#: ``SCOPE_HASH_FIELDS`` exactly as it stood on the parent commit, in order.
#: Pinning it is what turns the argument below from a plausible claim into a
#: proof: neither live config is reconstructible from this repository (both were
#: produced under a 150-symbol watchlist that is not the shipped default), so
#: the two hashes above cannot simply be recomputed. What CAN be checked is the
#: complete set of inputs to the hash function.
SCOPE_HASH_FIELDS_BEFORE_EXECUTION_SECTION = (
    "schema_version",
    "watchlist",
    "etf_universe",
    "allow_short_candidates",
    "enabled_horizons",
    "intraday_bar_size",
    "liquidity",
    "risk",
    "events",
    "data_quality",
    "quality_gates",
    "universe_filters",
    "commission_per_share",
    "commission_min_per_order",
    "slippage_bps",
    "half_spread_fill_penalty",
)


def test_execution_is_disabled_by_default() -> None:
    assert ResearchConfig().execution.enabled is False
    assert ExecutionConfig().enabled is False


def test_the_default_config_hash_did_not_move() -> None:
    assert ResearchConfig().config_hash == CONFIG_HASH_BEFORE_EXECUTION_SECTION


def test_execution_is_not_in_the_approval_scope_hash() -> None:
    assert "execution" not in ResearchConfig.SCOPE_HASH_FIELDS


def test_the_scope_field_tuple_did_not_move() -> None:
    """The tuple is the complete input list to ``config_hash``. Pinning it, in
    order, is the half of the proof that a projection argument needs."""
    assert ResearchConfig.SCOPE_HASH_FIELDS == SCOPE_HASH_FIELDS_BEFORE_EXECUTION_SECTION


def test_both_live_approval_config_hashes_are_unchanged() -> None:
    """The one that matters: **neither live approval moved out of scope.**

    The argument, and every step of it is asserted here rather than asserted
    about:

    1. ``config_hash`` is a pure projection — it hashes ``model_dump`` narrowed
       to ``SCOPE_HASH_FIELDS`` and nothing else (asserted below, and again in
       ``test_config_hash_is_computed_over_the_scope_fields_and_nothing_else``).
    2. ``SCOPE_HASH_FIELDS`` is byte-identical to the parent commit's
       (``test_the_scope_field_tuple_did_not_move``), and ``execution`` is not
       in it.
    3. The serialized shape of every scoped section is unchanged, pinned by the
       default config's hash (``test_the_default_config_hash_did_not_move``).

    A projection cannot see a key outside it, so a config that hashed to
    ``11b54aee…`` or ``fe365720…`` before this commit hashes to the same value
    after it — whatever its watchlist was. This is a proof rather than a
    recomputation because neither live config lives in this repository.
    """
    cfg = ResearchConfig()
    payload = cfg.model_dump(mode="json")

    # Step 1, restated as an executable claim: the hash of a payload is
    # unchanged by mutating ANY key outside SCOPE_HASH_FIELDS — including keys
    # that do not exist yet.
    scoped = {k: payload[k] for k in ResearchConfig.SCOPE_HASH_FIELDS if k in payload}
    assert cfg.config_hash == hash_payload(scoped)
    polluted = dict(payload)
    polluted["execution"] = {"enabled": True, "adapter_name": "anything"}
    polluted["a_section_invented_by_a_later_phase"] = {"whatever": [1, 2, 3]}
    assert (
        hash_payload({k: polluted[k] for k in ResearchConfig.SCOPE_HASH_FIELDS}) == cfg.config_hash
    )

    # Steps 2 and 3.
    assert ResearchConfig.SCOPE_HASH_FIELDS == SCOPE_HASH_FIELDS_BEFORE_EXECUTION_SECTION
    assert "execution" not in ResearchConfig.SCOPE_HASH_FIELDS
    assert cfg.config_hash == CONFIG_HASH_BEFORE_EXECUTION_SECTION

    # And the live hashes are recorded here verbatim, so a future edit to this
    # file cannot quietly change which values the argument is about.
    assert LIVE_APPROVAL_CONFIG_HASHES[1].startswith("fe365720c0b6")  # pragma: allowlist secret
    assert len({*LIVE_APPROVAL_CONFIG_HASHES}) == 2
    assert all(len(h) == 64 for h in LIVE_APPROVAL_CONFIG_HASHES)


def test_config_hash_is_computed_over_the_scope_fields_and_nothing_else() -> None:
    """The mechanism behind the claim about the two live approvals: whatever
    config produced them, its hash is a function of ``SCOPE_HASH_FIELDS`` only,
    so a new section outside that tuple cannot change it."""
    cfg = ResearchConfig()
    payload = cfg.model_dump(mode="json")
    scoped = {k: payload[k] for k in ResearchConfig.SCOPE_HASH_FIELDS if k in payload}
    assert cfg.config_hash == hash_payload(scoped)
    assert "execution" not in scoped


def test_toggling_every_execution_field_leaves_the_scope_hash_byte_identical() -> None:
    baseline = ResearchConfig().config_hash
    for overrides in (
        {"enabled": True},
        {"adapter_name": "some_vendor_paper"},
        {"enabled": True, "adapter_name": "some_vendor_paper"},
    ):
        assert ResearchConfig(execution=ExecutionConfig(**overrides)).config_hash == baseline


def test_the_exclusion_holds_for_a_non_default_config_too() -> None:
    """The live approvals were granted under a non-default watchlist; the
    property must hold for any config, not just the shipped defaults."""
    other = ResearchConfig(watchlist=("AAPL", "MSFT"), slippage_bps=7.0)
    with_execution = other.model_copy(
        update={"execution": ExecutionConfig(enabled=True, adapter_name="x")}
    )
    assert with_execution.config_hash == other.config_hash
    assert other.config_hash not in LIVE_APPROVAL_CONFIG_HASHES  # sanity: a different config


def test_the_full_hash_still_sees_execution_for_the_audit_trail() -> None:
    """``full_config_hash`` is for audit trails, never for scope matching — and
    it SHOULD move, because the section is a real change to the recorded
    configuration."""
    a = ResearchConfig()
    b = ResearchConfig(execution=ExecutionConfig(enabled=True))
    assert a.full_config_hash != b.full_config_hash
    assert a.config_hash == b.config_hash


def test_the_execution_section_is_frozen_and_rejects_unknown_fields() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ExecutionConfig(armed=True)  # type: ignore[call-arg]
