from httpx import ASGITransport, AsyncClient

from app.core.errors import GoalNotPermittedForMinorError
from app.main import create_app


async def test_health_returns_200_with_real_database_round_trip(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "reachable"}


async def test_app_error_produces_the_exact_problem_json_envelope() -> None:
    # A fresh app with one throwaway route, so this exercises the generic error
    # contract (spec 7.2) itself, not any endpoint T-02+ will build.
    app = create_app()

    @app.get("/api/v1/_test_only_boom")
    async def _boom() -> None:
        raise GoalNotPermittedForMinorError(
            detail="Permitted goals for this account: maintain, gain.",
            errors=[{"field": "goal", "code": "NOT_ALLOWED"}],
        )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        response = await ac.get("/api/v1/_test_only_boom")

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["type"] == "https://api.gymak.fitness/errors/goal-not-permitted-for-minor"
    assert body["title"] == "This goal is not available for users under 18"
    assert body["status"] == 422
    assert body["code"] == "GOAL_NOT_PERMITTED_FOR_MINOR"
    assert body["detail"] == "Permitted goals for this account: maintain, gain."
    assert body["errors"] == [{"field": "goal", "code": "NOT_ALLOWED"}]
    assert isinstance(body["trace_id"], str)
    assert len(body["trace_id"]) > 0


async def test_security_headers_present_on_a_normal_response(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")
    assert response.headers["Strict-Transport-Security"] == (
        "max-age=63072000; includeSubDomains; preload"
    )
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
