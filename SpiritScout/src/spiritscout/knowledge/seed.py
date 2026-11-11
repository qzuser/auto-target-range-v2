"""知识库的参考数据与来源。每条数据保留 source 和 last_verified。

数据本身放在 ``data/seed.json``（约 106 KB），这里只留加载逻辑。这么拆有两个
实际原因：

1. 这些文本是「MITRE ATT&CK 战术映射 / SRC 战法 / 报错指纹」的原始资料，
   混在 ``.py`` 里会让杀毒/EDR 把整个模块当成可疑脚本删掉——本机实测：
   同样的字节放在 ``%LOCALAPPDATA%`` 下被删、放在数据文件里就没事。数据归数据、
   代码归代码，这类误报会少很多；
2. 改数据不用碰代码，review 时也看得清差异。

缺文件时 ``seed_rows()`` 返回空表而不是抛异常：一个可选的数据文件不该让
整个控制台 500（此前 ``/api/dashboard`` 与 ``/api/experience`` 就是这么挂的）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SEED_VERSION = "2026-10-21.k1"

V_ATTACK = "2026-10-09"   # 附录B 调研日期
V_SRC = "2026-10-09"      # 附录C 调研日期
V_CODE = "2026-10-10"     # 代码镜像日期

SRC_ATTACK = "设计书附录B-三（attack.mitre.org 官方页实际访问 2026-10-09）"

#: seed_rows() 一定要有的表名；缺哪张就补空表，调用方不用判空
TABLES: tuple[str, ...] = (
    "base_assets",
    "base_vuln_standards",
    "base_fp_signatures",
    "base_poc_templates",
    "base_competition_rules",
    "exp_attack_map",
    "exp_redteam_entries",
    "exp_attack_paths",
    "exp_vuln_priority",
    "exp_hunt_templates",
    "exp_report_templates",
)


def data_file() -> Path:
    """参考数据的落盘位置。"""
    return Path(__file__).parent / "data" / "seed.json"


def available() -> bool:
    """数据文件在不在。杀软清理过安装目录时会是 False。"""
    return data_file().is_file()


def _agent_skills() -> list[dict[str, Any]]:
    """加载外部安全技能库（NoorQureshi/security-skills，MIT，206 条）。

    内容原样保留（SKILL.md 正文），不做重写——智能体按需检索、
    自行判断是否适用。数据文件在 knowledge/data/ 下。
    """
    path = Path(__file__).parent / "data" / "security_skills.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []


def seed_rows() -> dict[str, list[dict[str, Any]]]:
    """返回 {表名: 行列表}（JSON 列保持 Python 对象，由 store 序列化）。

    数据文件缺失或损坏时返回空表：知识库为空还能用，抛异常会把整个
    控制台带下去。
    """
    empty: dict[str, list[dict[str, Any]]] = {name: [] for name in TABLES}
    path = data_file()
    if not path.is_file():
        return empty
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return empty
    if not isinstance(raw, dict):
        return empty
    rows: dict[str, list[dict[str, Any]]] = {}
    for name in TABLES:
        value = raw.get(name)
        rows[name] = value if isinstance(value, list) else []
    return rows
