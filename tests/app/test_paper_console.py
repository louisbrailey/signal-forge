def test_console_requires_auth(client):
    assert client.get("/paper-console", follow_redirects=False).status_code == 303


def test_empty_console_honest_and_refreshes(registered_client):
    response = registered_client.get("/paper-console")
    assert response.status_code == 200
    assert "No paper account exists" in response.text
    assert "stale or unavailable" in response.text
    assert "every 30s" in response.text
    assert "Research signal only" in response.text
