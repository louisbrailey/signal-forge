import json
from datetime import date

import pytest

from signalforge.data.accounting_snapshot import fetch_accounting_snapshot


class Adapter:
    def __init__(self, payload=None):
        self.calls = []
        self.payload = payload

    def _request(self, path):
        self.calls.append(path)
        return json.dumps(self.payload or {"status": "OK", "adjusted": False, "results": []})


def test_atomic_resume_and_cached_hash_validation(tmp_path):
    a = Adapter()
    first = fetch_accounting_snapshot(a, tmp_path, ["SPY"], date(2024, 1, 1), date(2024, 2, 1))
    assert len(a.calls) == 3
    assert (
        fetch_accounting_snapshot(a, tmp_path, ["SPY"], date(2024, 1, 1), date(2024, 2, 1)) == first
    )
    assert len(a.calls) == 3
    p = tmp_path / first["records"][0]["file"]
    record = json.loads(p.read_text())
    record["raw"] += " "
    p.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="hash"):
        fetch_accounting_snapshot(a, tmp_path, ["SPY"], date(2024, 1, 1), date(2024, 2, 1))


def test_partial_endpoint_does_not_claim_complete_snapshot(tmp_path):
    a = Adapter(
        {"status": "OK", "adjusted": False, "results": [], "next_url": "https://evil.invalid"}
    )
    with pytest.raises(ValueError, match="incomplete"):
        fetch_accounting_snapshot(a, tmp_path, ["SPY"], date(2024, 1, 1), date(2024, 2, 1))
    assert not (tmp_path / "manifest.json").exists()
    assert len(a.calls) == 1


def test_storage_cap_blocks_before_writing_raw_data(tmp_path):
    with pytest.raises(ValueError, match="storage cap"):
        fetch_accounting_snapshot(
            Adapter(), tmp_path, ["SPY"], date(2024, 1, 1), date(2024, 2, 1), max_bytes=100
        )
    assert not list(tmp_path.iterdir())
