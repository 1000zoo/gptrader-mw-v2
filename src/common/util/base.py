from datetime import datetime
from typing import List

from src.common.model.base import Meta


def get_meta(status: int, msg: str, ok: bool):
    return Meta(
        metaTime=datetime.now(),
        status=status,
        msg= msg,
        ok=ok)

def success_meta(status: int = 200, msg: str = "success"):
    return get_meta(status, msg, True)

def fail_meta(status: int = 400, msg: str = "fail"):
    return get_meta(status, msg, False)

def to_data(data):
    if not isinstance(data, List):
        data = [data]
    return data