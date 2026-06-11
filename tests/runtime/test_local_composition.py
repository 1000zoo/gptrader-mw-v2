from src.runtime import RuntimeSettings, create_local_app, create_local_runtime


def test_local_runtime_reports_health_details() -> None:
    runtime = create_local_runtime(RuntimeSettings(symbol="ETHUSDT"))

    details = runtime.health_details()

    assert details["mode"] == "local"
    assert details["symbol"] == "ETHUSDT"
    assert details["dependencies"][0] == {
        "name": "exchange",
        "status": "local",
        "detail": "external exchange disabled",
    }


def test_local_app_exposes_health_and_readiness_routes() -> None:
    app = create_local_app(RuntimeSettings(symbol="ETHUSDT"))
    health = next(route for route in app.routes if route.path == "/health")
    readiness = next(route for route in app.routes if route.path == "/readiness")
    status = next(route for route in app.routes if route.path == "/status")

    assert health.endpoint()["details"]["symbol"] == "ETHUSDT"
    assert readiness.endpoint()["details"]["ready_for"] == "local"
    assert status.endpoint()["data"]["trade_controls"] == "disabled"
    assert status.endpoint()["data"]["live_order_path"] == "disabled"
