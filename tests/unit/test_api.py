import hashlib

from fastapi.testclient import TestClient

from main import create_app
from packages.common.storage import MemoryObjectStorage


HEADERS = {"X-User-ID": "user-1", "X-User-Email": "user@example.test"}


def test_upload_flow_and_external_health():
    storage = MemoryObjectStorage()
    app = create_app(database_url="sqlite://", storage=storage, create_schema=True)
    client = TestClient(app)

    assert client.post("/api/v1/surveys", json={}).status_code == 401
    survey_response = client.post(
        "/api/v1/surveys",
        headers=HEADERS,
        json={
            "latitude": 55.75,
            "longitude": 37.61,
            "gps_accuracy_m": 4.5,
            "camera_direction_deg": 180,
            "notes": [{"text": "northbound"}],
        },
    )
    assert survey_response.status_code == 201
    survey_id = survey_response.json()["id"]

    content = b"small-test-video"
    upload_response = client.post(
        "/api/v1/videos/upload-sessions",
        headers=HEADERS,
        json={
            "survey_id": survey_id,
            "filename": "road.mp4",
            "content_type": "video/mp4",
            "size_bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        },
    )
    assert upload_response.status_code == 201, upload_response.text
    upload = upload_response.json()
    etag = storage.put_part(upload["upload_id"], 1, content)

    completed = client.post(
        f"/api/v1/videos/{upload['video_id']}/complete-upload",
        headers=HEADERS,
        json={"parts": [{"part_number": 1, "etag": etag}]},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["state"] == "queued"

    fetched = client.get(f"/api/v1/videos/{upload['video_id']}", headers=HEADERS)
    assert fetched.status_code == 200
    assert fetched.json()["object_key"].startswith("originals/")

    health = client.get("/api/v1/integrations/external-database/health")
    assert health.json() == {
        "status": "not_configured",
        "state": "dns_nxdomain",
        "retryable": False,
    }
