# -*- coding: utf-8 -*-
"""RViz 外部进程管理。

目标：GUI 顶部按钮只负责发起/停止，真正的 rviz2 子进程在独立
QThread 内启动，并把 stdout/stderr 逐行转发到主日志。
"""
from __future__ import annotations

import os
import shlex
import signal
import subprocess
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, Signal

from .log_service import LogLevel, LogService


_REPO_ROOT = Path(__file__).resolve().parents[2]
RVIZ_CONFIG_PATH = _REPO_ROOT / "rviz2" / "rviz" / "n10p.rviz"


class _RvizRunner(QThread):
    """单次 rviz2 运行线程。

    使用 QThread 子类是有意为之：stop() 可从 GUI 线程直接调用，不依赖
    worker 线程事件循环，避免子进程阻塞读 stdout 时无法响应 queued slot。
    """

    process_started = Signal(int)
    output_line = Signal(str)
    process_failed = Signal(str)
    process_finished = Signal(int, str)

    def __init__(self, shell_cmd: str, cwd: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._shell_cmd = shell_cmd
        self._cwd = str(cwd)
        self._proc: subprocess.Popen[str] | None = None
        self._lock = threading.RLock()
        self._stop_requested = False

    def run(self) -> None:  # noqa: D401
        """线程入口：启动进程、转发输出、等待退出。"""
        ret = -1
        reason = "未启动"
        try:
            if self._stop_requested:
                self.process_finished.emit(0, "启动前已取消")
                return
            kwargs: dict = dict(
                cwd=self._cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            if os.name == "posix":
                kwargs["preexec_fn"] = os.setsid

            proc = subprocess.Popen(["bash", "-lc", self._shell_cmd], **kwargs)
            with self._lock:
                self._proc = proc
            self.process_started.emit(proc.pid)
            if self._stop_requested:
                self.stop()

            assert proc.stdout is not None
            while True:
                line = proc.stdout.readline()
                if line:
                    self.output_line.emit(line.rstrip("\r\n"))
                    continue
                ret_now = proc.poll()
                if ret_now is not None:
                    ret = int(ret_now)
                    break
                time.sleep(0.02)

            # 尽量把管道剩余输出读完。
            for rest in proc.stdout.readlines():
                if rest:
                    self.output_line.emit(rest.rstrip("\r\n"))

            if self._stop_requested:
                reason = "已按请求停止"
            elif ret == 0:
                reason = "进程正常退出"
            else:
                reason = f"进程异常退出，code={ret}"
        except FileNotFoundError as exc:
            reason = "启动失败"
            self.process_failed.emit(f"启动 rviz2 失败：{exc}")
        except Exception as exc:  # 兜底，避免线程静默死亡
            reason = "线程异常"
            self.process_failed.emit(f"rviz 线程异常：{exc!r}")
        finally:
            with self._lock:
                self._proc = None
            self.process_finished.emit(ret, reason)

    def stop(self) -> None:
        """请求停止子进程。可从 GUI 线程直接调用。"""
        self._stop_requested = True
        with self._lock:
            proc = self._proc
        if proc is None or proc.poll() is not None:
            return
        try:
            if os.name == "posix":
                # RViz2/rclcpp 对 Ctrl-C(SIGINT) 的退出路径更干净；超时后再 SIGKILL。
                os.killpg(os.getpgid(proc.pid), signal.SIGINT)
            else:
                proc.terminate()
        except ProcessLookupError:
            return
        except Exception as exc:
            self.process_failed.emit(f"停止 rviz2 失败：{exc!r}")

    def force_kill(self) -> None:
        """SIGTERM 无响应时强制结束。"""
        with self._lock:
            proc = self._proc
        if proc is None or proc.poll() is not None:
            return
        try:
            if os.name == "posix":
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            else:
                proc.kill()
        except ProcessLookupError:
            return
        except Exception as exc:
            self.process_failed.emit(f"强制结束 rviz2 失败：{exc!r}")


class RvizProcessManager(QObject):
    """主线程侧 RViz 管理器。"""

    running_changed = Signal(bool)

    def __init__(self, log_service: LogService, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._log = log_service
        self._runner: _RvizRunner | None = None
        self._stopping = False

    @property
    def is_running(self) -> bool:
        return self._runner is not None and self._runner.isRunning()

    def start(self) -> bool:
        """启动 rviz2。若已在运行，仅记录日志并返回 True。"""
        if self.is_running:
            self._log.info("rviz", "rviz2 已在运行")
            return True

        if not RVIZ_CONFIG_PATH.is_file():
            self._log.error("rviz", f"配置文件不存在：{RVIZ_CONFIG_PATH}")
            return False

        shell_cmd = self._build_shell_command()
        self._runner = _RvizRunner(shell_cmd=shell_cmd, cwd=_REPO_ROOT, parent=self)
        self._runner.process_started.connect(self._on_started)
        self._runner.output_line.connect(self._on_output_line)
        self._runner.process_failed.connect(self._on_failed)
        self._runner.process_finished.connect(self._on_finished)
        self._runner.finished.connect(self._runner.deleteLater)

        self._stopping = False
        self._log.info("rviz", f"启动：rviz2 -d {RVIZ_CONFIG_PATH}")
        self._runner.start()
        self.running_changed.emit(True)
        return True

    def stop(self, reason: str = "用户请求", wait_ms: int = 0) -> None:
        """停止 rviz2。GUI 关闭时传 wait_ms，保证不留后台。"""
        runner = self._runner
        if runner is None:
            return
        self._stopping = True
        if runner.isRunning():
            self._log.info("rviz", f"停止 rviz2：{reason}")
            runner.stop()
            QTimer.singleShot(3000, self._force_kill_if_needed)
            if wait_ms > 0 and not runner.wait(wait_ms):
                self._log.warn("rviz", "rviz2 未按时退出，执行强制结束")
                runner.force_kill()
                runner.wait(1000)
        else:
            self._runner = None

    def _build_shell_command(self) -> str:
        override = os.environ.get("LINGXIAO_RVIZ_COMMAND", "").strip()
        if override:
            return override
        cfg = shlex.quote(str(RVIZ_CONFIG_PATH))
        # 显式 source ROS Humble；若 GUI 是从桌面启动，也能找到 rviz2。
        return (
            "if [ -f /opt/ros/humble/setup.bash ]; then "
            "source /opt/ros/humble/setup.bash; "
            "fi; "
            f"exec rviz2 -d {cfg}"
        )

    def _force_kill_if_needed(self) -> None:
        runner = self._runner
        if runner is not None and runner.isRunning() and self._stopping:
            self._log.warn("rviz", "rviz2 对停止请求无响应，强制结束")
            runner.force_kill()

    def _on_started(self, pid: int) -> None:
        self._log.info("rviz", f"rviz2 已启动，pid={pid}")

    def _on_output_line(self, line: str) -> None:
        if not line:
            return
        lower = line.lower()
        if "error" in lower or "fatal" in lower:
            level = LogLevel.ERROR
        elif "warn" in lower or "warning" in lower:
            level = LogLevel.WARN
        else:
            level = LogLevel.INFO
        self._log.log(level, "rviz", line)

    def _on_failed(self, message: str) -> None:
        self._log.error("rviz", message)

    def _on_finished(self, code: int, reason: str) -> None:
        if self._stopping:
            self._log.info("rviz", f"rviz2 已停止，code={code}")
        elif code == 0:
            self._log.info("rviz", f"rviz2 退出：{reason}")
        else:
            self._log.warn("rviz", f"rviz2 退出：{reason}")
        self._runner = None
        self._stopping = False
        self.running_changed.emit(False)
