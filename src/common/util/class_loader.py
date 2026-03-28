import importlib

from src.common.exception import InvalidRequestException


def load_class(path: str, name: str, cls):
    try:
        module = importlib.import_module(path)
    except Exception as exc:
        raise InvalidRequestException(
            f"Failed to import strategy module: {path}"
        ) from exc

    strategy_cls = getattr(module, name, None)
    if strategy_cls is None:
        raise InvalidRequestException(
            f"Strategy class not found: {name}"
        )

    if not isinstance(strategy_cls, type) or not issubclass(strategy_cls, cls):
        raise InvalidRequestException(
            f"Strategy class must inherit IStrategy: {name}"
        )

    try:
        return strategy_cls()
    except Exception as exc:
        raise InvalidRequestException(
            f"Failed to instantiate strategy class: {name}"
        ) from exc