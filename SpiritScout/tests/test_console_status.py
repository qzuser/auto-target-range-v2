"""终端窗口的两件事：端口真通了才喊「可以打开」，之后定时报状态。

原来只有一行 ``print("控制台: http://…")`` 打头，可那时监听还没建起来——照着链接
点过去可能连不上；打完就进 ``uvicorn.run()`` 阻塞，窗口从此一言不发，跑到第几小时、
手上几个会话、吃了多少内存，全得自己开任务管理器看。

改成：等 TCP 真能连上再提示一次，随后按 ``STATUS_INTERVAL`` 报状态。这里钉住
三个易错点——探活要用真连接不用猜时间、状态行不能因为取数失败把服务带崩、
服务已经在退的时候别再多喊一句。
"""

from __future__ import annotations

import contextlib
import io
import socket
import unittest
from typing import Any
from unittest import mock

from spiritscout import __main__ as cli

# --------------------------------------------------------------- 桩

class _Session:
    def __init__(self, status: str) -> None:
        self.status = status


class _Manager:
    def __init__(self, statuses: list[str] | None = None, boom: bool = False) -> None:
        self._statuses = statuses or []
        self._boom = boom

    def list(self) -> list[_Session]:
        if self._boom:
            raise RuntimeError("数据库被锁了")
        return [_Session(s) for s in self._statuses]


class _State:
    def __init__(self, manager: _Manager) -> None:
        self.manager = manager


class _App:
    def __init__(self, statuses: list[str] | None = None, boom: bool = False) -> None:
        self.state = _State(_Manager(statuses, boom))


class _Server:
    """uvicorn.Server 的最小替身：只看 started / should_exit 两个字段。"""

    def __init__(self, started: bool = True, should_exit: bool = False) -> None:
        self.started = started
        self.should_exit = should_exit
        self._exit_after = 0

    def exit_after(self, checks: int) -> _Server:
        """再过 checks 次 tick 就置 should_exit，让守护循环自己收尾。"""
        self._exit_after = checks
        return self

    def tick(self) -> None:
        if self._exit_after:
            self._exit_after -= 1
            if self._exit_after == 0:
                self.should_exit = True


@contextlib.contextmanager
def _listening() -> Any:
    """占一个随机端口并真的 listen，模拟「服务已经能接了」。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    try:
        yield sock.getsockname()[1]
    finally:
        sock.close()


def _closed_port() -> int:
    """绑一下就放掉，拿一个确定没人在听的端口号。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


# --------------------------------------------------------------- 探活

class PortProbeTests(unittest.TestCase):
    def test_listening_port_reads_as_open(self) -> None:
        with _listening() as port:
            self.assertTrue(cli._port_open("127.0.0.1", port),
                            "端口在 listen，探活却说关着")

    def test_closed_port_reads_as_closed(self) -> None:
        self.assertFalse(cli._port_open("127.0.0.1", _closed_port()),
                         "没人听的端口被当成开着——就绪提示会提前喊")


# --------------------------------------------------------------- 时长

class DurationTests(unittest.TestCase):
    def test_minutes_and_hours(self) -> None:
        self.assertEqual(cli._duration(0), "00:00")
        self.assertEqual(cli._duration(65), "01:05")
        self.assertEqual(cli._duration(3725), "1:02:05")

    def test_fractional_seconds_do_not_leak_into_the_string(self) -> None:
        self.assertEqual(cli._duration(59.9), "00:59")


# --------------------------------------------------------------- 状态行

class StatusLineTests(unittest.TestCase):
    def test_reports_uptime_and_session_counts(self) -> None:
        line = cli._status_line(_App(["running", "running", "completed"]), 65)
        self.assertIn("[状态]", line)
        self.assertIn("已运行 01:05", line)
        self.assertIn("会话 3（运行中 2）", line)

    def test_a_broken_manager_degrades_instead_of_raising(self) -> None:
        line = cli._status_line(_App(boom=True), 0)
        self.assertIn("[状态]", line)
        self.assertIn("会话 0（运行中 0）", line,
                      "取不到会话数时该退到 0，而不是把整个状态行丢掉")

    def test_psutil_missing_still_prints_the_rest(self) -> None:
        with mock.patch.dict("sys.modules", {"psutil": None}):
            line = cli._status_line(_App(["running"]), 10)
        self.assertIn("已运行 00:10", line)
        self.assertIn("会话 1（运行中 1）", line)
        self.assertNotIn("内存", line, "没有 psutil 就不该假装知道内存")


# --------------------------------------------------------------- 守护线程

class WatchConsoleTests(unittest.TestCase):
    def _run(self, server: _Server, port: int, app: _App | None = None, *,
             timeout: float = 1.0) -> tuple[str, str]:
        """跑一遍 _watch_console，收走 stdout / stderr。

        时钟和 sleep 都换成假的：真按 60 秒间隔跑，一条用例就得等一分钟；
        而只换 sleep 不换时钟，超时分支永远等不到。假秒表每次前进 10ms，
        sleep 照传进来的秒数走，两条分支都能在毫秒内走到。
        """
        out, err = io.StringIO(), io.StringIO()
        app = app or _App()
        clock = {"now": 0.0}

        def fake_monotonic() -> float:
            clock["now"] += 0.01
            return clock["now"]

        def fake_sleep(seconds: float) -> None:
            clock["now"] += max(float(seconds), 0.0)
            server.tick()

        with mock.patch.object(cli, "STATUS_INTERVAL", 0.01):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                with mock.patch.object(cli.time, "monotonic", fake_monotonic), \
                        mock.patch.object(cli.time, "sleep", fake_sleep):
                    cli._watch_console(server, app, "127.0.0.1", port, timeout=timeout)
        return out.getvalue(), err.getvalue()

    def test_says_ready_once_the_port_actually_accepts(self) -> None:
        with _listening() as port:
            server = _Server().exit_after(2)
            out, _ = self._run(server, port)
        self.assertIn("[就绪] 浏览器可以打开了", out)
        self.assertIn(f"127.0.0.1:{port}", out)

    def test_reports_status_repeatedly_after_being_ready(self) -> None:
        with _listening() as port:
            server = _Server().exit_after(3)
            out, _ = self._run(server, port)
        self.assertGreaterEqual(out.count("[状态]"), 2,
                                "就绪后应持续报状态，而不是只报一条")

    def test_stays_quiet_when_the_server_is_already_shutting_down(self) -> None:
        server = _Server(should_exit=True)
        out, _err = self._run(server, _closed_port())
        self.assertNotIn("[就绪]", out, "都已经在退了，不该再喊可以打开")
        self.assertEqual(out.strip(), "")

    def test_warns_when_the_port_never_opens(self) -> None:
        # 端口一直关着 → 靠 deadline 超时退出就绪等待，走「还没连上」这一支
        server = _Server(started=True).exit_after(2)
        out, err = self._run(server, _closed_port(), timeout=0.1)
        self.assertNotIn("[就绪]", out)
        self.assertIn("还没连上", err, "一直连不上要给提示，不能让窗口哑着")


if __name__ == "__main__":
    unittest.main()
