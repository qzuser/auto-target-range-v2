"""Run one unittest target with Windows-safe temporary-directory cleanup."""

from __future__ import annotations

import sys
import tempfile
import unittest

_original_init = tempfile.TemporaryDirectory.__init__


def _windows_safe_init(directory: tempfile.TemporaryDirectory, *args, **kwargs) -> None:
    # Windows may still hold a SQLite file briefly after the test assertion.
    # Deferring deletion to the OS cleaner avoids touching unrelated live
    # connections while keeping functional failures visible.
    kwargs["ignore_cleanup_errors"] = True
    _original_init(directory, *args, **kwargs)


tempfile.TemporaryDirectory.__init__ = _windows_safe_init


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: test_worker.py <module-or-module.Class>", file=sys.stderr)
        return 2
    suite = unittest.defaultTestLoader.loadTestsFromName(sys.argv[1])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
