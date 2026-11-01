"""按模型统计 token 用量的聚合逻辑与接口。"""
from __future__ import annotations

import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from spiritscout.config.settings import SystemConfig, WorkspaceConfig
from spiritscout.gateway.usage import UsageLedger
from spiritscout.web.usage_stats import UNKNOWN_MODEL, collect

DAY = 86400


def _cfg(root: Path) -> SystemConfig:
    return SystemConfig(workspace=WorkspaceConfig(root=str(root)),
                        models_config_path=str(root / "models.yaml"))


def _write(root: Path, name: str, rows: list[dict]) -> None:
    """把几条用量记录写进对应账本（``name`` 为空 = 控制台根账本）。"""
    base = root if not name else root / "sessions" / name
    base.mkdir(parents=True, exist_ok=True)
    ledger = UsageLedger(base / "usage.db")
    try:
        for row in rows:
            ledger.append(row)
    finally:
        pass


class CollectTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.cfg = _cfg(self.root)
        self.now = time.time()

    def test_groups_all_ledgers_by_model(self) -> None:
        _write(self.root, "", [
            {"ts": self.now - 60, "tokens": 100, "input_tokens": 80,
             "output_tokens": 20, "model": "cn:glm-5.3-flash", "cost_usd": 0.01},
        ])
        _write(self.root, "sess-a", [
            {"ts": self.now - 120, "tokens": 300, "input_tokens": 200,
             "output_tokens": 100, "model": "cn:glm-5.3-flash", "cost_usd": 0.03},
            {"ts": self.now - 180, "tokens": 50, "model": "prism-ml/bonsai-27b"},
        ])
        data = collect(self.cfg, period="today", now=self.now)
        by_model = {m["model"]: m for m in data["models"]}
        self.assertEqual(by_model["cn:glm-5.3-flash"]["calls"], 2)
        self.assertEqual(by_model["cn:glm-5.3-flash"]["tokens"], 400)
        self.assertEqual(by_model["cn:glm-5.3-flash"]["input"], 280)
        self.assertEqual(by_model["cn:glm-5.3-flash"]["output"], 120)
        self.assertEqual(by_model["prism-ml/bonsai-27b"]["tokens"], 50)
        self.assertEqual(data["totals"]["tokens"], 450)
        self.assertEqual(data["totals"]["models"], 2)
        self.assertEqual(data["ledgers"], 2)
        # 第一条按 token 降序，占比合计约等于 1
        self.assertEqual(data["models"][0]["model"], "cn:glm-5.3-flash")
        self.assertAlmostEqual(sum(m["share"] for m in data["models"]), 1.0, places=3)

    def test_period_window_filters_out_old_calls(self) -> None:
        _write(self.root, "", [
            {"ts": self.now - 40 * DAY, "tokens": 999, "model": "cn:glm-5.3-flash"},
            {"ts": self.now - 2 * DAY, "tokens": 10, "model": "cn:glm-5.3-flash"},
        ])
        week = collect(self.cfg, period="7d", now=self.now)
        self.assertEqual(week["totals"]["tokens"], 10)
        everything = collect(self.cfg, period="all", now=self.now)
        self.assertEqual(everything["totals"]["tokens"], 1009)

    def test_unknown_model_is_bucketed_not_dropped(self) -> None:
        _write(self.root, "sess-x", [{"ts": self.now - 5, "tokens": 7}])
        data = collect(self.cfg, period="today", now=self.now)
        self.assertEqual([m["model"] for m in data["models"]], [UNKNOWN_MODEL])
        self.assertEqual(data["totals"]["tokens"], 7)

    def test_empty_workspace_is_honest(self) -> None:
        data = collect(self.cfg, period="7d", now=self.now)
        self.assertEqual(data["models"], [])
        self.assertEqual(data["totals"]["tokens"], 0)
        self.assertEqual(data["ledgers"], 0)

    def test_daily_series_has_one_point_per_day(self) -> None:
        _write(self.root, "", [
            {"ts": self.now - 1 * DAY, "tokens": 10, "model": "a"},
            {"ts": self.now - 1 * DAY, "tokens": 5, "model": "a"},
            {"ts": self.now - 2 * DAY, "tokens": 7, "model": "b"},
        ])
        data = collect(self.cfg, period="7d", now=self.now)
        days = [d["date"] for d in data["daily"]]
        self.assertEqual(len(days), len(set(days)), "同一天只出现一次")
        total = sum(d["tokens"] for d in data["daily"])
        self.assertEqual(total, 22)

    def test_bad_period_falls_back_to_week(self) -> None:
        data = collect(self.cfg, period="nonsense", now=self.now)
        self.assertEqual(data["period"], "7d")


class RouteTests(unittest.TestCase):
    def test_route_registered(self) -> None:
        from fastapi import FastAPI

        from spiritscout.web.routes.usage import mount_usage

        app = FastAPI()
        with TemporaryDirectory(ignore_cleanup_errors=True) as raw:
            mount_usage(app, cfg=_cfg(Path(raw)))
            paths = {getattr(route, "path", "") for route in app.routes}
        self.assertIn("/api/usage/stats", paths)


if __name__ == "__main__":   # pragma: no cover
    unittest.main()
