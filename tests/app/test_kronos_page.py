from tests.app.conftest import _csrf


def test_kronos_authentication(client):
    assert client.get("/kronos", follow_redirects=False).status_code == 303
    assert client.get("/kronos/results/1", follow_redirects=False).status_code == 303


def test_kronos_page_labels(registered_client):
    r = registered_client.get("/kronos")
    assert r.status_code == 200
    assert "HISTORICAL REPLAY" in r.text
    assert "pretraining" in r.text.lower()
    assert "No replay experiments recorded" in r.text


def test_kronos_post_csrf_and_watchlist(registered_client):
    assert registered_client.post("/kronos/replay", data={"symbol": "AAPL"}).status_code == 403
    r = registered_client.post(
        "/kronos/replay",
        data={"symbol": "UNKNOWN", "csrf_token": _csrf(registered_client, "/kronos")},
    )
    assert r.status_code == 400


def test_kronos_missing_data_is_not_fake_result(registered_client):
    r = registered_client.post(
        "/kronos/replay", data={"symbol": "AAPL", "csrf_token": _csrf(registered_client, "/kronos")}
    )
    assert r.status_code == 200
    assert "Insufficient persisted Massive daily history" in r.text
    assert "No replay experiments recorded" in r.text


def test_replay_persist_export_and_no_write_lock_during_inference(registered_client, monkeypatch):
    from sqlalchemy import select

    from signalforge.app.routers import kronos
    from signalforge.db.models import AuditLog
    from signalforge.db.session import session_scope

    def infer(db, symbol, horizon):
        assert not db.get_bind().get_execution_options().get("sqlite_write", False)
        return {
            "ticker": symbol,
            "horizon": horizon,
            "model": "test-model",
            "source": "test-only",
            "source_latency_categories": ["END_OF_DAY"],
            "generated_at": "2026-01-01T00:00:00+00:00",
            "input_start": "2025-01-01",
            "input_end": "2025-12-20",
            "heldout_start": "2025-12-22",
            "heldout_end": "2025-12-26",
            "mae": 1.0,
            "baseline_mae": 2.0,
            "points": [
                {
                    "date": "2025-12-22",
                    "actual": 102,
                    "predicted": 101,
                    "baseline": 100,
                    "low": 100,
                    "high": 102,
                }
            ],
        }

    monkeypatch.setattr(kronos, "replay", infer)
    r = registered_client.post(
        "/kronos/replay", data={"symbol": "AAPL", "csrf_token": _csrf(registered_client, "/kronos")}
    )
    assert r.status_code == 200
    assert "Model error is lower on this replay only" in r.text
    assert "Recorded input latency: END_OF_DAY" in r.text
    with session_scope() as s:
        row = s.scalar(select(AuditLog).where(AuditLog.action == "kronos.replay"))
        assert row is not None
        run_id = row.id
    exported = registered_client.get(f"/kronos/results/{run_id}")
    assert exported.status_code == 200
    assert exported.json()["source"] == "test-only"
    assert registered_client.get(f"/kronos?run_id={run_id}").status_code == 200


def test_kronos_kill_switch_blocks_work(registered_client):
    from signalforge.killswitch import get_kill_switch

    token = _csrf(registered_client, "/kronos")
    get_kill_switch().engage(reason="test")
    assert (
        registered_client.post(
            "/kronos/replay", data={"symbol": "AAPL", "csrf_token": token}
        ).status_code
        == 423
    )
