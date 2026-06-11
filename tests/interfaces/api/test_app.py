from src.interfaces.api import create_app


def test_create_app_exposes_health() -> None:
    app = create_app(health_provider=lambda: {"mode": "testnet"})

    route = next(route for route in app.routes if route.path == "/health")

    assert route.endpoint() == {
        "ok": True,
        "status": "healthy",
        "details": {"mode": "testnet"},
    }
