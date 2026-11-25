"""Desktop parent lifetime guard tests."""

from __future__ import annotations

import os
import threading
import unittest
from unittest.mock import patch

from spiritscout.desktop_lifecycle import (
    PARENT_PID_ENV,
    PARENT_START_ENV,
    install_parent_watchdog,
    parent_alive,
)


class DesktopLifecycleTests(unittest.TestCase):
    def test_current_process_is_alive_and_missing_process_is_not(self) -> None:
        self.assertTrue(parent_alive(os.getpid()))
        self.assertFalse(parent_alive(2_147_483_647))

    def test_watchdog_exits_when_parent_is_gone(self) -> None:
        exits: list[int] = []
        completed = threading.Event()

        def exit_callback(code: int) -> None:
            exits.append(code)
            completed.set()

        with patch.dict(
            os.environ,
            {PARENT_PID_ENV: "2147483647", PARENT_START_ENV: ""},
            clear=False,
        ):
            thread = install_parent_watchdog(
                exit_callback=exit_callback,
                interval_seconds=0.01,
            )
            self.assertIsNotNone(thread)
            self.assertTrue(completed.wait(2), "watchdog did not exit")

        self.assertEqual(exits, [0])

    def test_watchdog_is_not_started_outside_desktop(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(install_parent_watchdog())

    def test_watchdog_accepts_explicit_desktop_parent_pid(self) -> None:
        exits: list[int] = []
        completed = threading.Event()

        def exit_callback(code: int) -> None:
            exits.append(code)
            completed.set()

        with patch.dict(os.environ, {}, clear=True):
            thread = install_parent_watchdog(
                exit_callback=exit_callback,
                interval_seconds=0.01,
                parent_pid_override=2_147_483_647,
            )
            self.assertIsNotNone(thread)
            self.assertTrue(completed.wait(2))

        self.assertEqual(exits, [0])


if __name__ == "__main__":
    unittest.main()
