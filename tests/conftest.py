import sys
from pathlib import Path
import types

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

if "loguru" not in sys.modules:
    class DummyLogger:
        def __getattr__(self, name):
            def _noop(*args, **kwargs):
                return None

            return _noop

        def bind(self, **kwargs):
            return self

    loguru_module = types.SimpleNamespace(logger=DummyLogger())
    sys.modules["loguru"] = loguru_module

if "fastapi" not in sys.modules:
    class DummyHTTPException(Exception):
        def __init__(self, status_code: int, detail: str):
            self.status_code = status_code
            self.detail = detail

    class DummyRouter:
        def __init__(self, *args, **kwargs):
            return None

        def get(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

        def post(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

    def Header(default=None):
        return default

    fastapi_module = types.SimpleNamespace(
        APIRouter=DummyRouter,
        Header=Header,
        HTTPException=DummyHTTPException,
    )
    sys.modules["fastapi"] = fastapi_module

if "sqlalchemy" not in sys.modules:
    sqlalchemy_module = types.ModuleType("sqlalchemy")

    def text(value):
        return value

    sqlalchemy_module.text = text
    exc_module = types.ModuleType("sqlalchemy.exc")

    class SQLAlchemyError(Exception):
        pass

    exc_module.SQLAlchemyError = SQLAlchemyError
    sys.modules["sqlalchemy"] = sqlalchemy_module
    sys.modules["sqlalchemy.exc"] = exc_module
    ext_module = types.ModuleType("sqlalchemy.ext")
    asyncio_module = types.ModuleType("sqlalchemy.ext.asyncio")

    def create_async_engine(*args, **kwargs):
        return None

    def async_sessionmaker(*args, **kwargs):
        return lambda: None

    asyncio_module.create_async_engine = create_async_engine
    asyncio_module.async_sessionmaker = async_sessionmaker
    sys.modules["sqlalchemy.ext"] = ext_module
    sys.modules["sqlalchemy.ext.asyncio"] = asyncio_module

if "pydantic" not in sys.modules:
    pydantic_module = types.ModuleType("pydantic")

    class BaseModel:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

        def model_dump(self, exclude_none: bool = False, exclude_defaults: bool = False):
            data = dict(self.__dict__)
            if exclude_none:
                data = {k: v for k, v in data.items() if v is not None}
            return data

    pydantic_module.BaseModel = BaseModel
    sys.modules["pydantic"] = pydantic_module

if "binance" not in sys.modules:
    binance_module = types.ModuleType("binance")
    um_futures_module = types.ModuleType("binance.um_futures")
    error_module = types.ModuleType("binance.error")

    class UMFutures:
        def __init__(self, *args, **kwargs):
            return None

    class ClientError(Exception):
        pass

    um_futures_module.UMFutures = UMFutures
    error_module.ClientError = ClientError
    sys.modules["binance"] = binance_module
    sys.modules["binance.um_futures"] = um_futures_module
    sys.modules["binance.error"] = error_module

if "dotenv" not in sys.modules:
    dotenv_module = types.ModuleType("dotenv")

    def load_dotenv(*args, **kwargs):
        return None

    dotenv_module.load_dotenv = load_dotenv
    sys.modules["dotenv"] = dotenv_module

if "httpx" not in sys.modules:
    httpx_module = types.ModuleType("httpx")

    class DummyResponse:
        def __init__(self):
            self.status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {}

    def get(*args, **kwargs):
        return DummyResponse()

    def post(*args, **kwargs):
        return DummyResponse()

    httpx_module.get = get
    httpx_module.post = post
    httpx_module.HTTPError = Exception
    sys.modules["httpx"] = httpx_module

if "openai" not in sys.modules:
    openai_module = types.ModuleType("openai")

    class OpenAIError(Exception):
        pass

    class OpenAI:
        def __init__(self, *args, **kwargs):
            self.chat = types.SimpleNamespace(
                completions=types.SimpleNamespace(create=lambda *a, **k: {})
            )

    openai_module.OpenAI = OpenAI
    openai_module.OpenAIError = OpenAIError
    sys.modules["openai"] = openai_module
    openai_types_module = types.ModuleType("openai.types")
    openai_types_chat_module = types.ModuleType("openai.types.chat")

    class ChatCompletion:
        pass

    openai_types_chat_module.ChatCompletion = ChatCompletion
    sys.modules["openai.types"] = openai_types_module
    sys.modules["openai.types.chat"] = openai_types_chat_module
