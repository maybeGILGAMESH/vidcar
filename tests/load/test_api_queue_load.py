from fastapi.testclient import TestClient

from main import create_app


def test_api_remains_responsive_for_twenty_survey_requests():
    app = create_app(database_url="sqlite://", create_schema=True)
    client = TestClient(app)
    headers = {"X-User-ID": "load-user"}
    for index in range(20):
        response = client.post(
            "/api/v1/surveys",
            headers=headers,
            json={
                "latitude": 55 + index / 100,
                "longitude": 37,
                "gps_accuracy_m": 5,
            },
        )
        assert response.status_code == 201
    assert client.get("/health").json() == {"status": "ok"}
