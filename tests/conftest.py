import sys
import types
from pathlib import Path

from dotenv import load_dotenv

from src.common.db.connection import init_db

init_db()

ROOT = Path(__file__).resolve().parents[1]

load_dotenv()

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

if "dotenv" not in sys.modules:
    dotenv_module = types.ModuleType("dotenv")

    def load_dotenv(*args, **kwargs):
        return None

    dotenv_module.load_dotenv = load_dotenv
    sys.modules["dotenv"] = dotenv_module

