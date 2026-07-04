from fastapi.testclient import TestClient

from scheduler.main import app


def test_smoke_login_and_metrics() -> None:
    with TestClient(app) as client:
        login = client.post(
            "/api/auth/login",
            json={"email": "demo@example.com", "password": "demo1234"},
        )
        assert login.status_code == 200
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        queues = client.get("/api/queues", headers=headers)
        assert queues.status_code == 200
        assert len(queues.json()) >= 1

        jobs = client.get("/api/jobs", headers=headers)
        assert jobs.status_code == 200
        assert jobs.json()["total"] >= 1

        metrics = client.get("/api/metrics", headers=headers)
        assert metrics.status_code == 200
        assert "jobs" in metrics.json()
        assert "workers" in metrics.json()
