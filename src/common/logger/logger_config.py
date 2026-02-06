from __future__ import annotations

import logging
import os
import sys
import time
from contextlib import suppress
from pathlib import Path
from typing import Optional

from loguru import logger

# ========= 기본 포맷 ========= #
CONSOLE_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>"
)

FILE_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
    "{level: <8} | "
    "{process.name}:{thread.name} | "
    "{name}:{function}:{line} - "
    "{message}"
)

# ========= 표준 logging → loguru 브리지 ========= #
class InterceptHandler(logging.Handler):
    """표준 logging 로그를 loguru로 위임하는 핸들러."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = logging.currentframe(), 2
        # 호출 스택에서 logging 모듈 프레임을 건너뛰기
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back  # type: ignore[attr-defined]
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def _bool_env(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.lower() in {"1", "true", "t", "yes", "y"}


# ========= SQLAlchemy 로그 최소화 ========= #
class SqlAlchemyMinimalFilter(logging.Filter):
    """SQLAlchemy echo 로그에서 트랜잭션/캐시 노이즈 제거."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if msg.startswith("BEGIN") or msg.startswith("COMMIT") or msg.startswith("ROLLBACK"):
            return False
        if "cached since" in msg:
            return False
        return True


# ========= 초기화 함수 ========= #
def setup_logging(
    app_name: str = "app",
    log_dir: str | os.PathLike[str] = "logs",
    level: str = "INFO",
    rotation: str = None,
    retention: str = None,
    compression: str = None,
    enqueue: Optional[bool] = None,
) -> None:
    """loguru 전역 로거를 초기화한다.

    Args:
        app_name: 로그 파일 접두사에 포함될 이름
        log_dir: 로그 저장 디렉토리 (없으면 생성)
        level: 최소 레벨 (DEBUG/INFO/WARNING/ERROR)
        rotation: 파일 회전 조건 (예: "1 day", "100 MB", "00:00")
        retention: 보관 기간 (예: "7 days", "1 month")
        compression: 압축 형식 (예: "zip", "gz")
        enqueue: True면 비동기 큐 사용(멀티프로세스/스레드 안전)
    """

    # 환경변수 우선 적용
    level = os.getenv("LOG_LEVEL", level)
    log_tz = os.getenv("LOG_TZ", "Asia/Seoul")
    log_dir = os.getenv("LOG_DIR", str(log_dir))
    rotation = os.getenv("LOG_ROTATION", rotation or "1 day")
    retention = os.getenv("LOG_RETENTION", retention or "30 days")
    compression = os.getenv("LOG_COMPRESSION", compression or "zip")
    enqueue = _bool_env("LOG_ENQUEUE", True if enqueue is None else enqueue)
    sql_echo = _bool_env("SQL_ECHO", False)
    sql_echo_minimal = _bool_env("SQL_ECHO_MINIMAL", True)

    # 로그 타임존 설정 (컨테이너 기본 UTC → KST)
    if log_tz:
        os.environ["TZ"] = log_tz
        if hasattr(time, "tzset"):
            time.tzset()

    Path(log_dir).mkdir(parents=True, exist_ok=True)

    # 기본 핸들러 제거(중복 방지)
    logger.remove()

    # 콘솔 핸들러
    logger.add(
        sys.stdout,
        level=level,
        format=CONSOLE_FORMAT,
        backtrace=True,
        diagnose=False,
        enqueue=enqueue,
    )

    # 파일 핸들러(일자별)
    file_pattern = os.path.join(str(log_dir), f"{app_name}_{{time:YYYY-MM-DD}}.log")
    logger.add(
        file_pattern,
        level=level,
        format=FILE_FORMAT,
        rotation=rotation,
        retention=retention,
        compression=compression,
        backtrace=True,
        diagnose=False,
        enqueue=enqueue,
    )

    src_file_pattern = os.path.join(str(log_dir), f"{app_name}_src_{{time:YYYY-MM-DD}}.log")
    logger.add(
        src_file_pattern,
        level=level,
        format=FILE_FORMAT,
        rotation=rotation,
        retention=retention,
        compression=compression,
        backtrace=True,
        diagnose=False,
        enqueue=enqueue,
        filter=lambda r: r["name"].startswith("src.")
    )


    # 표준 logging 루트 로거를 loguru로 라우팅
    logging.root.handlers = [InterceptHandler()]
    logging.root.setLevel(getattr(logging, level, logging.INFO))

    # 일반적으로 자주 시끄러운 로거 레벨 조정(필요 시 수정)
    for noisy in (
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
        "asyncio",
        "sqlalchemy",
        "sqlalchemy.pool",
        "sqlalchemy.dialects",
        "asyncpg",
    ):
        with suppress(Exception):
            logging.getLogger(noisy).handlers = [InterceptHandler()]
            logging.getLogger(noisy).setLevel(getattr(logging, level, logging.ERROR))

    # SQLAlchemy engine 로그는 SQL_ECHO에 따라 제어
    with suppress(Exception):
        engine_logger = logging.getLogger("sqlalchemy.engine.Engine")
        engine_logger.handlers = [InterceptHandler()]
        engine_logger.setLevel(logging.INFO if sql_echo else logging.ERROR)
        if sql_echo and sql_echo_minimal:
            engine_logger.addFilter(SqlAlchemyMinimalFilter())


# ========= FastAPI 전용 미들웨어 ========= #

from fastapi import FastAPI, Request
from starlette.responses import Response

from src.common.exception.exception_handler import handle_top_level_exception



def install_fastapi_middleware(app: FastAPI) -> None:
    if app is None:
        return

    @app.middleware("http")
    async def _log_requests(request: Request, call_next):
        start = time.perf_counter()
        method = request.method
        url_path = request.url.path
        query = request.url.query
        client = request.client.host if request.client else "-"
        logger.bind(endpoint=url_path).info(f"▶️ {method} {url_path}{('?' + query) if query else ''} from {client}")
        try:
            response: "Response" = await call_next(request)
            elapsed_ms = (time.perf_counter() - start) * 1000
            status = response.status_code
            if status >= 500:
                logger.error(f"⛔ {method} {url_path} {status} - {elapsed_ms:.2f} ms")
            elif status >= 400:
                logger.warning(f"⚠️ {method} {url_path} {status} - {elapsed_ms:.2f} ms")
            else:
                logger.info(f"✅ {method} {url_path} {status} - {elapsed_ms:.2f} ms")
            return response
        except Exception as e:  # 미들웨어에서 잡힌 예외도 로깅
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.exception(f"💥 {method} {url_path} 500 - {elapsed_ms:.2f} ms: {e}")
            await handle_top_level_exception("web_app", f"{method} {url_path}", e)
            raise


# ========= 편의 데코레이터 ========= #
def catch_errors(func):
    """함수 예외 자동 로깅 데코레이터 (동기 함수용)."""
    return logger.catch(reraise=True)(func)


def catch_errors_async(func):
    """코루틴 예외 자동 로깅 데코레이터 (비동기 함수용)."""
    async def wrapper(*args, **kwargs):
        with logger.catch(reraise=True):
            return await func(*args, **kwargs)
    return wrapper


if __name__ == "__main__":
    setup_logging(app_name="demo", log_dir="logs", level="DEBUG")
    logger.debug("디버그 로그")
    logger.info("정보 로그")
    logger.warning("경고 로그")
    try:
        1 / 0
    except ZeroDivisionError:
        logger.exception("예외 로그")
