"""本地 MCP 的接入模板：选中一项，命令与参数直接填进表单。

本地 MCP 就是 stdio 子进程（``npx`` / ``uvx`` / 项目自带可执行文件），手写
``command`` 和 ``args`` 很容易漏掉一个 ``-y``、少一个根目录，接上去之后只在
调用工具时才报错。这里把常见几家的启动方式收成模板，参数位置写成
``{PLACEHOLDER}``，选完再替换。

模板只描述**怎么启动**，不预置任何密钥：需要 token 的服务（如 fetch 的
代理、私有包源）通过「环境变量」专用字段填，走加密密钥库，不进配置文件。
"""

from __future__ import annotations

import shutil
from typing import Any

#: id 用于前端选中；``requires`` 里的可执行文件在本机找不到时标成不可用
LOCAL_PRESETS: list[dict[str, Any]] = [
    {
        "id": "filesystem",
        "label": "文件系统（官方 filesystem）",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "{ROOT}"],
        "default_risk": "intrusive",
        "placeholder_hint": "{ROOT} 换成允许读写的绝对目录（多个目录可以再追加参数）。",
        "requires": ["npx"],
    },
    {
        "id": "memory",
        "label": "记忆库（官方 memory）",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-memory"],
        "default_risk": "intrusive",
        "placeholder_hint": "知识图存本机；换机器前记得把数据目录一起搬走。",
        "requires": ["npx"],
    },
    {
        "id": "sequential-thinking",
        "label": "顺序推理（官方 sequential-thinking）",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"],
        "default_risk": "readonly",
        "placeholder_hint": "纯推理工具，不碰目标，适合当规划辅助。",
        "requires": ["npx"],
    },
    {
        "id": "time",
        "label": "时间与换算（uvx mcp-server-time）",
        "transport": "stdio",
        "command": "uvx",
        "args": ["mcp-server-time"],
        "default_risk": "readonly",
        "placeholder_hint": "时区换算；会话里跨时区比对时间戳时用得上。",
        "requires": ["uvx"],
    },
    {
        "id": "fetch",
        "label": "网页抓取（uvx mcp-server-fetch）",
        "transport": "stdio",
        "command": "uvx",
        "args": ["mcp-server-fetch"],
        "default_risk": "intrusive",
        "placeholder_hint": "抓公开页面；要走代理就填环境变量 HTTPS_PROXY。",
        "requires": ["uvx"],
    },
    {
        "id": "git",
        "label": "仓库操作（uvx mcp-server-git）",
        "transport": "stdio",
        "command": "uvx",
        "args": ["mcp-server-git", "--repository", "{REPO}"],
        "default_risk": "intrusive",
        "placeholder_hint": "{REPO} 换成仓库绝对路径；留空则用当前工作目录。",
        "requires": ["uvx"],
    },
    {
        "id": "sqlite",
        "label": "SQLite 查询（uvx mcp-server-sqlite）",
        "transport": "stdio",
        "command": "uvx",
        "args": ["mcp-server-sqlite", "--db-path", "{DB}"],
        "default_risk": "intrusive",
        "placeholder_hint": "{DB} 换成只读副本的路径更稳妥，别直连生产库。",
        "requires": ["uvx"],
    },
    {
        "id": "venv-stdio",
        "label": "本项目 venv 里的 MCP（stdio）",
        "transport": "stdio",
        "command": "{PYTHON}",
        "args": ["-m", "{MODULE}", "--stdio"],
        "default_risk": "intrusive",
        "placeholder_hint": "{PYTHON} 填 venv 解释器绝对路径，{MODULE} 填模块名。",
        "requires": [],
    },
    {
        "id": "custom",
        "label": "自定义（手写 command / args）",
        "transport": "stdio",
        "command": "",
        "args": [],
        "default_risk": "intrusive",
        "placeholder_hint": "自备可执行文件；stdin/stdout 走 MCP 的 stdio 传输。",
        "requires": [],
    },
]

_BY_ID = {item["id"]: item for item in LOCAL_PRESETS}


def list_presets() -> list[dict[str, Any]]:
    """给前端用：附带本机是否装得上（缺 ``npx``/``uvx`` 时置灰而不是等到报错）。"""
    items: list[dict[str, Any]] = []
    for item in LOCAL_PRESETS:
        missing = [name for name in item.get("requires", []) if shutil.which(name) is None]
        items.append({**item, "available": not missing, "missing": missing})
    return items


def preset_config(preset_id: str) -> dict[str, Any]:
    """取一个模板的接入字段（可直接并进「配置内容」的 JSON）。

    不带 ``id``/``label`` 这类展示字段，也不带 ``enabled``——启用与否是用户
    保存时的选择，模板不替用户决定。未知 id 回落到自定义模板。
    """
    item = _BY_ID.get(str(preset_id or "").strip()) or _BY_ID["custom"]
    return {
        "transport": item["transport"],
        "command": item["command"],
        "args": list(item["args"]),
        "env": {},
        "default_risk": item["default_risk"],
    }


def placeholders(preset_id: str) -> list[str]:
    """模板里需要替换的 ``{XXX}`` 占位符，按出现顺序去重。"""
    item = _BY_ID.get(str(preset_id or "").strip()) or _BY_ID["custom"]
    seen: list[str] = []
    for text in [item["command"], *item["args"]]:
        start = 0
        while (left := text.find("{", start)) != -1:
            right = text.find("}", left)
            if right == -1:
                break
            token = text[left:right + 1]
            if token not in seen:
                seen.append(token)
            start = right + 1
    return seen
