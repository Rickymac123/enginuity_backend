import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize("commit", ["a1b2c3d", None], ids=["set", "absent"])
def test_health_returns_only_ok_and_commit(monkeypatch, commit):
    from app.main import app

    monkeypatch.setenv("HEALTH_TEST_UNRELATED", "dummy-value")
    if commit is None:
        monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    else:
        monkeypatch.setenv("RENDER_GIT_COMMIT", commit)

    # Avoid running database startup for this endpoint-only test.
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body == {"ok": True, "commit": commit}
    assert body["ok"] is True
