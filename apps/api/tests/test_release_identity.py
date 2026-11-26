from fastapi.testclient import TestClient

from bc_api.main import create_app


def test_release_headers_come_from_server_configuration_not_the_request(settings, run_input):
    commit = "a" * 40
    settings = settings.model_copy(update={"release_commit": commit, "release_id": "r-fixture"})
    run_input["messages"][0]["content"] = "hello"
    run_input["forwardedProps"] = {"bc": {"version": 2, "mode": "general"}}
    with TestClient(
        create_app(settings),
        headers={
            "Origin": "http://localhost:3000",
            "X-BC-API-Release": "b" * 40,
        },
    ) as client:
        capabilities = client.get("/api/capabilities")
        assert capabilities.status_code == 200
        assert capabilities.headers["X-BC-API-Release"] == commit
        assert capabilities.headers["X-BC-API-Deployment"] == "r-fixture"
        reply = client.post("/api/agent", json=run_input)
        assert reply.status_code == 200
        assert reply.headers["X-BC-API-Release"] == commit
        assert reply.headers["X-BC-API-Deployment"] == "r-fixture"
        assert '"type":"RUN_FINISHED"' in reply.text


def test_unstamped_local_app_does_not_echo_a_forged_release_header(settings):
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/capabilities", headers={"X-BC-API-Release": "b" * 40})
        assert response.status_code == 200
        assert "X-BC-API-Release" not in response.headers
