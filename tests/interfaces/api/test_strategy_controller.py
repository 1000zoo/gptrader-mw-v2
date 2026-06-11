from src.interfaces.api.strategy_controller import create_strategy_router


class RecordingUseCase:
    def __init__(self) -> None:
        self.commands = []

    def execute(self, command):
        self.commands.append(command)
        return {"registered": True}


def test_register_strategy_uses_injected_command_factory() -> None:
    usecase = RecordingUseCase()
    router = create_strategy_router(
        register_usecase=usecase,
        register_command_factory=lambda payload: ("register", payload["id"]),
    )
    endpoint = next(route for route in router.routes if route.path == "/strategies/register").endpoint

    response = endpoint({"id": "s1"})

    assert response == {"ok": True, "data": {"registered": True}}
    assert usecase.commands == [("register", "s1")]
