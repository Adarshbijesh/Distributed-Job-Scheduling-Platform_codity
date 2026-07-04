import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scheduler.main import app


def main() -> None:
    with TestClient(app) as client:
        login = client.post(
            "/api/auth/login",
            json={"email": "demo@example.com", "password": "demo1234"},
        )
        print("login", login.status_code)
        login.raise_for_status()
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        queues = client.get("/api/queues", headers=headers)
        print("queues", queues.status_code, len(queues.json()))
        queues.raise_for_status()

        jobs = client.get("/api/jobs", headers=headers)
        print("jobs", jobs.status_code, jobs.json()["total"])
        jobs.raise_for_status()

        metrics = client.get("/api/metrics", headers=headers)
        print("metrics", metrics.status_code, metrics.json())
        metrics.raise_for_status()


if __name__ == "__main__":
    main()
