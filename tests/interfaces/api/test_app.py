from src.interfaces.api import create_app


def test_create_app_exposes_health() -> None:
    app = create_app(health_provider=lambda: {"mode": "testnet"})

    route = next(route for route in app.routes if route.path == "/health")

    assert route.endpoint() == {
        "ok": True,
        "status": "healthy",
        "details": {"mode": "testnet"},
    }


def test_create_app_exposes_readiness() -> None:
    app = create_app(readiness_provider=lambda: {"mode": "local"})

    route = next(route for route in app.routes if route.path == "/readiness")

    assert route.endpoint() == {
        "ok": True,
        "status": "ready",
        "details": {"mode": "local"},
    }


def test_create_app_exposes_status() -> None:
    app = create_app(status_provider=lambda: {"runtime": "local"})

    route = next(route for route in app.routes if route.path == "/status")

    assert route.endpoint() == {"ok": True, "data": {"runtime": "local"}}
