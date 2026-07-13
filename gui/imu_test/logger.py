# -*- coding: utf-8 -*-
"""IMU 测试台独立日志系统。

设计要点：
- **独立于现有 LogService**：现有 LogService 依赖 Qt 信号且面向 UI 日志区；
  本模块基于 Python 标准 logging，可在 Qt App 尚未创建时使用，且不干扰现有日志。
- **双输出**：同时输出到控制台（stderr）与文件，便于实时观察 + 事后排查。
- **跨平台日志目录**：
  - Linux: ``~/.local/share/imu_test/logs/``（遵循 XDG）
  - Windows: ``%LOCALAPPDATA%/imu_test/logs/``
  - 兜底: ``~/.imu_test/logs/``
- **单例**：全包共用一个 logger（名为 ``imu_test``），避免重复挂 handler。
- **UTF-8**：文件强制 UTF-8，避免中文乱码（本项目历史坑）。

用法::

    from gui.imu_test.logger import get_logger
    log = get_logger()
    log.info("数据流已启动: %.1f Hz", fps)
"""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from typing import Optional

_LOGGER_NAME = "imu_test"
_MAX_BYTES = 2 * 1024 * 1024  # 单文件上限 2 MB
_BACKUP_COUNT = 5             # 保留 5 个历史文件
_FMT = "%(asctime)s [%(levelname)s] [%(module)s] %(message)s"
_DATEFMT = "%H:%M:%S"

# 模块级缓存，保证单例
_logger_cache: Optional[logging.Logger] = None


def _resolve_log_dir() -> str:
    """跨平台解析日志目录，确保目录存在。绝不抛异常。"""
    try:
        if sys.platform == "win32":
            base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
            log_dir = os.path.join(base, "imu_test", "logs")
        else:
            base = os.environ.get("XDG_DATA_HOME") or os.path.join(
                os.path.expanduser("~"), ".local", "share"
            )
            log_dir = os.path.join(base, "imu_test", "logs")
        os.makedirs(log_dir, exist_ok=True)
        return log_dir
    except Exception:
        # 兜底目录
        fallback = os.path.join(os.path.expanduser("~"), ".imu_test", "logs")
        try:
            os.makedirs(fallback, exist_ok=True)
        except Exception:
            pass
        return fallback


def get_log_dir() -> str:
    """返回当前日志目录（供 UI「打开日志目录」使用）。"""
    return _resolve_log_dir()


def get_log_file_path() -> str:
    """返回当前主日志文件的完整路径。"""
    return os.path.join(_resolve_log_dir(), "imu_test.log")


def get_logger() -> logging.Logger:
    """获取（并在首次调用时初始化）IMU 测试台的单例 logger。"""
    global _logger_cache
    if _logger_cache is not None:
        return _logger_cache

    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    # 不向 root 传播，避免与其他库/现有日志重复输出
    logger.propagate = False

    # 防止重复挂 handler（例如模块被多次 import 或热重载）
    if logger.handlers:
        _logger_cache = logger
        return logger

    formatter = logging.Formatter(_FMT, datefmt=_DATEFMT)

    # 控制台 handler（INFO 及以上，避免刷屏）
    console = logging.StreamHandler(stream=sys.stderr)
    console.setLevel(logging.INFO)
    console.setFormatter(formatter)
    logger.addHandler(console)

    # 文件 handler（DEBUG 全量，滚动）
    try:
        file_handler = RotatingFileHandler(
            get_log_file_path(),
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception as exc:  # 文件不可写时不致命，仅控制台可用
        logger.warning("文件日志初始化失败，仅控制台输出：%s", exc)

    logger.debug("IMU 测试台日志系统已初始化，日志目录=%s", get_log_dir())
    _logger_cache = logger
    return logger
