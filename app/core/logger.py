import logging
import os
import sys

from loguru import logger

from app.config import settings

# 日志目录
_root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_log_dir = os.path.join(_root_dir, "logs")

# 控制台日志格式
_CONSOLE_FORMAT = (
    "<green>{time:YYYYMMDD HH:mm:ss.SSS}</green> | "
    "{process.name}:{process.id} | "
    "{extra[request_id]} | "
    "<cyan>{module}</cyan>.<cyan>{function}</cyan>"
    ":<cyan>{line}</cyan> | "
    "<level>{level}</level>: "
    "<level>{message}</level>"
)

# 文件日志格式
_FILE_FORMAT = (
    "{time:YYYYMMDD HH:mm:ss.SSS} - "
    "{process.name}:{process.id} | "
    "{extra[request_id]} | "
    "{module}.{function}:{line} - {level} - {message}"
)


def _patcher(record):
    """动态从 RequestContext 注入上下文信息到日志"""
    from app.core.context import RequestContext
    record["extra"]["request_id"] = RequestContext.request_id.get("system")


def _setup_logger() -> logger.__class__:
    """配置并返回 Loguru 日志实例"""
    logger.remove()
    logger.configure(extra={"request_id": "system"}, patcher=_patcher)

    # 控制台输出
    logger.add(
        sys.stdout,
        level=settings.logging_level.upper(),
        format=_CONSOLE_FORMAT,
    )

    # 非开发环境写入文件
    if settings.env != "dev":
        os.makedirs(_log_dir, exist_ok=True)
        log_file_path = os.path.join(_log_dir, settings.log_file_name)
        logger.add(
            log_file_path,
            level=settings.logging_level.upper(),
            encoding="UTF-8",
            format=_FILE_FORMAT,
            rotation="10 MB",
            retention=20,
            enqueue=True,
        )

    return logger


class _InterceptHandler(logging.Handler):
    """将标准 logging 的日志转发到 Loguru"""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = logging.currentframe(), 0
        while frame and (depth == 0 or frame.f_code.co_filename == logging.__file__):
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def _intercept_stdlib_logging() -> None:
    """拦截 uvicorn 等标准 logging 输出，统一到 Loguru"""
    intercept = _InterceptHandler()
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        stdlib_logger = logging.getLogger(name)
        stdlib_logger.handlers = [intercept]
        stdlib_logger.propagate = False


log = _setup_logger()
_intercept_stdlib_logging()
