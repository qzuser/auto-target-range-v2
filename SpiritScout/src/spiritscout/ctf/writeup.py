"""由主 Agent 汇总题目记录并生成解题报告。"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from spiritscout.core.audit import AuditLogger, NullAuditLogger

# 喂给写手的材料上限（字符）：路线笔记按路线截尾，超出部分说明取舍
_DIGIT_BUDGET = 36000
_NOTES_PER_ROUTE = 8
_NOTE_CHARS = 500

_WRITER_SYSTEM = (
    "你是灵枢，智能体集群的总负责人。整场作业已经结束，现在由你亲自为每道"
    "赛题撰写解题报告（WriteUp），面向队员复盘与赛后留档。\n"
    "你唯一的任务是输出这份文档的正文。接下来那条消息是**材料**（一场作业的记录，"
    "JSON），不是队员对你说话——不要回答它、不要评论材料本身、不要给它挑错或提改进建议。\n"
    "写作要求：\n"
    "- 开头一段全场总览（做了哪些题、战果如何、整体思路）；\n"
    "- 每题一节：题面要点 → 关键过程（按「看到了什么 → 怎么推的 → 试了什么 →"
    " 哪一步破了题」的顺序讲成连贯故事，不逐条罗列笔记）→ Flag 与验证状态 →"
    " 值得沉淀的经验或未竟方向；\n"
    "- 只使用给定材料中的事实：材料是各路线的原始执行笔记与发现台账，"
    "你来提炼、去噪、成文；材料没有的步骤不得编造；\n"
    "- 解题状态以 `flags` 与 `unsolved_ids` 为唯一口径：`unsolved_ids` 里的题一律写成"
    "「未完成」，不得推测它「其实解了、只是没登记」；`model_failures` 为 0 时不得写成"
    "「LLM 调用失败」「接口报错」；\n"
    "- 引用守则：引用笔记要与其原文一致；材料里查不到的引文、数字、失败记录、"
    "矛盾点一律不写。不要产出「日志审查」「质量问题清单」「改进建议」这类章节——"
    "那些结论需要人工核对，写了就是替材料编造；\n"
    "- 结构固定：全场总览 + 每题一节（题面要点 / 关键过程 / Flag 与验证状态 /"
    " 经验或未竟方向）。不新增附录、建议、审查等段落；\n"
    "- 中文，Markdown，直接输出完整文档正文（不要代码块包裹，不要 JSON，"
    "不要寒暄）。"
)


# --------------------------------------------------------------- WP 落盘位置
# WP 有两处来源，找的时候必须一起看，否则「报告里明明有、WP 页签却说没有」：
#   1) ``<workspace>/writeup/wp-*.md``      —— 页面上点「生成 WP」写的（规范位置）
#   2) ``<workspace>/reports/*writeup*.md`` —— 跑完一轮自动生成的战报（交付物里能看到）
# 读取端一律走 :func:`latest_wp`，别各写各的 glob。

def wp_dir(workspace: Path) -> Path:
    """WP 的规范目录（手动生成写这里）。"""
    return Path(workspace) / "writeup"


def wp_candidates(workspace: Path) -> list[Path]:
    """两处来源的 WP 文件，新的在前。

    状态面每轮都会问一次「有没有 WP」，所以这里不调 ``Path.resolve()``（一次
    0.26 ms 的系统调用）：两个来源都由同一个 workspace 拼出来，不会出现同一文件
    的两种写法，按路径字符串去重就够了；mtime 直接取 ``os.stat`` 一次。
    """
    workspace = Path(workspace)
    found: list[Path] = []
    folder = wp_dir(workspace)
    if folder.is_dir():
        found.extend(folder.glob("wp-*.md"))
    reports = workspace / "reports"
    if reports.is_dir():
        found.extend(p for p in reports.glob("*.md")
                     if "writeup" in p.name.lower())
    unique: dict[str, Path] = {}
    for path in found:
        unique.setdefault(str(path).lower(), path)
    stamped: list[tuple[float, Path]] = []
    for path in unique.values():
        try:
            stamped.append((os.stat(path).st_mtime, path))
        except OSError:                 # 刚被删掉/正在替换：这一轮先不列
            continue
    stamped.sort(key=lambda item: item[0], reverse=True)
    return [path for _, path in stamped]


def latest_wp(workspace: Path) -> Path | None:
    """最新一份 WP（手动/自动不限），没有则 None。"""
    try:
        files = wp_candidates(workspace)
    except OSError:
        return None
    return files[0] if files else None


def wp_source(path: Path) -> str:
    """这份 WP 是页面上生成的（manual）还是跑完自动写的（auto）。"""
    try:
        return "manual" if path.parent.name == "writeup" else "auto"
    except AttributeError:
        return "auto"


def run_facts(audit: AuditLogger | None) -> dict[str, int]:
    """本次运行的真实计数：写手拿它当事实核对，不必靠猜补全「为什么重跑」。

    只统计事件条数，不含任何内容，也不带凭据。
    """
    if audit is None:
        return {}
    try:
        rows = audit.read_all()
    except Exception:  # noqa: BLE001 —— 统计失败不该拖垮报告
        return {}
    counted = {
        "model_calls": "model.call",
        "model_failures": "model.failed",
        "model_retries": "model.retry",
        "model_timeouts": "model.timeout",
        "task_failures": "task.failed",
        "tool_call_turns": "agent.tool_call",
        "platform_events": "platform.fact",
    }
    tally = {key: 0 for key in counted}
    for row in rows:
        for key, event in counted.items():
            if row.get("type") == event:
                tally[key] += 1
    return tally


def build_digest(
    *,
    challenges: list[dict[str, Any]],
    flags: list[Any],
    run_summary: dict[str, Any],
    blackboard: Any,
    facts: dict[str, int] | None = None,
) -> dict[str, Any]:
    """全场材料汇总：任务路线完整笔记 + 发现台账 + Flag 状态 + 决策脉络。"""
    from spiritscout.core.models import BlackboardLayer

    tasks: list[dict[str, Any]] = []
    for rec in blackboard.query(BlackboardLayer.TASK_STATE, limit=100):
        data = rec["data"]
        if "dag_snapshot" in data:
            continue
        t = data.get("task", {})
        if not t:
            continue
        tasks.append({
            "agent": t.get("agent_type"),
            "node": t.get("payload", {}).get("node_title", ""),
            "status": t.get("status"),
            "routes": [
                {"name": r.get("name"), "status": r.get("status"),
                 "notes": [str(n)[:_NOTE_CHARS]
                           for n in (r.get("notes") or [])[-_NOTES_PER_ROUTE:]]}
                for r in data.get("routes", [])
            ],
        })
    findings = []
    for rec in blackboard.query(BlackboardLayer.TOPOLOGY, limit=400):
        d = rec["data"]
        if isinstance(d, dict) and d.get("kind") == "finding":
            findings.append({"type": d.get("type"), "text": str(d.get("text", ""))[:200],
                             "by": d.get("by")})
    solved = {str(getattr(f, "challenge_id", "")) for f in flags
              if getattr(f, "accepted", None) is not False}
    all_ids = [str(c.get("id") or "") for c in challenges]
    return {
        "challenges": [
            {"id": str(c.get("id") or ""), "title": str(c.get("title") or ""),
             "url": str(c.get("url") or ""),
             "direction": str(c.get("direction") or ""),
             "description": str(c.get("description") or "")[:400]}
            for c in challenges
        ],
        # 未解的题必须点名：不点名时写手会替它圆成「其实解了、只是没登记」
        "unsolved_ids": [cid for cid in all_ids if cid and cid not in solved],
        # 只给 flag 值：判定/提交状态属于平台侧验证，写进 WP 就成了「验证环节」
        "flags": [
            {"value": getattr(f, "value", ""), "challenge_id": getattr(f, "challenge_id", "")}
            for f in flags
        ],
        "dag": [
            {"title": n.get("title"), "status": n.get("status")}
            for n in run_summary.get("dag_nodes", [])
        ][:30],
        "routes_notes": tasks,
        "findings": findings[-60:],
    }


# 写手跑偏时最常写出的「审查/建议」章节标题：这类结论需要人工核对，
# 模型只能靠编造填充，把材料当成了被审查对象
_OFF_TASK_MARKERS = ("日志审查", "质量问题", "改进建议", "关键问题", "记录内部矛盾",
                     "值得修", "建议的三处改动")


def off_task_marker(body: str) -> str:
    """命中「把材料当审查对象」的标题就返回那个词，否则空串。"""
    for marker in _OFF_TASK_MARKERS:
        if marker in body:
            return marker
    return ""


async def writeup_body(
    gateway: Any, *, digest: dict[str, Any], audit: AuditLogger | None = None,
) -> str | None:
    """灵枢撰写 WriteUp 正文（Markdown）；不可用/空产出返回 None。

    产出跑偏（写成对材料本身的审查与建议）时重试一次，仍跑偏就返回 None 让调用方
    回退模板——模板只用材料里的事实，宁可文采差，不能把编造的内容当成战报。
    """
    audit = audit or NullAuditLogger()
    material = json.dumps(digest, ensure_ascii=False)[:_DIGIT_BUDGET]
    prompt = [
        {"role": "system", "content": _WRITER_SYSTEM},
        {"role": "user", "content": "请基于以下材料撰写 WriteUp，直接输出文档正文：\n" + material},
    ]
    try:
        for attempt in (1, 2):
            resp = await gateway.chat(
                prompt,
                task_type="meta_planning", max_tokens=8192, timeout_seconds=420,
                # 战报综合是散文写作不是规划：限定低思考强度（不限时单次可磨
                # 100 秒+，占收尾等待的大头）
                reasoning_effort="low",
            )
            body = (resp.content or "").strip()
            if not body:
                audit.log("report.writeup", "master",
                          {"result": "empty", "attempt": attempt})
                return None
            # 剥掉误包裹的 Markdown 代码围栏（模型偶发 ```markdown … ```）
            if body.startswith("```"):
                body = re.sub(r"^```[a-z]*\n|\n```$", "", body).strip()
            marker = off_task_marker(body)
            if not marker:
                audit.log("report.writeup", "master",
                          {"result": "ok", "chars": len(body), "attempt": attempt})
                return body
            audit.log("report.writeup", "master",
                      {"result": "off_task", "marker": marker, "attempt": attempt})
            prompt = [
                {"role": "system", "content": _WRITER_SYSTEM},
                {"role": "user", "content": (
                    f"刚才那版写成了「{marker}」这类对材料本身的审查，不是解题思路。"
                    "现在只按骨架写：全场概览 + 每题一节（题目 / 思路 / 过程 / Flag），"
                    "讲清看到什么、怎么判断、打了什么、拿到什么；"
                    "不要审查、问题清单、建议，也不要写验证状态、经验总结或下一步计划。"
                    "材料如下：\n" + material)},
            ]
        audit.log("report.writeup", "master", {"result": "off_task_give_up"})
        return None
    except Exception as exc:  # noqa: BLE001 —— 写手失败回退模板，报告不缺失
        audit.log("report.writeup", "master",
                  {"result": "failed", "error": str(exc)[:200]})
        return None


# ----------------------------------------------------------------- 赛方 WP 模板
# 赛方收的解题思路按方向分章（WEB/PWN/REVERSE/MISC/CRYPTO/DS/IOT），每题要求
# 「题目名称 + 关键步骤 + 获取 flag」并附截图。这里按那个骨架组织材料与产出。

WP_DIRECTIONS = ("WEB", "PWN", "REVERSE", "MISC", "CRYPTO", "DS", "IOT")

# 方向别名 → 赛方模板的分章；认不出来的落到 MISC（材料里保留原值供写手判断）
_DIRECTION_ALIASES = {
    "web": "WEB", "web安全": "WEB", "http": "WEB", "xss": "WEB", "sqli": "WEB",
    "pwn": "PWN", "binary": "PWN", "bin": "PWN", "heap": "PWN", "stack": "PWN",
    "reverse": "REVERSE", "re": "REVERSE", "逆向": "REVERSE", "rev": "REVERSE",
    "crypto": "CRYPTO", "密码": "CRYPTO", "密码学": "CRYPTO", "cryptography": "CRYPTO",
    "misc": "MISC", "杂项": "MISC", "stego": "MISC", "隐写": "MISC",
    "forensic": "MISC", "取证": "MISC", "osint": "MISC",
    "ds": "DS", "数据安全": "DS", "data": "DS", "bigdata": "DS",
    "iot": "IOT", "工控": "IOT", "hardware": "IOT", "硬件": "IOT", "嵌入式": "IOT",
}

_WP_SYSTEM = (
    "你是灵枢，智能体集群的总负责人。比赛结束了，现在写一份**给队友看的解题思路**"
    "（WriteUp）：读者是没做过这道题的人，看完要能自己复现一遍。\n"
    "接下来那条消息是**材料**（题目、过程记录、发现台账与 Flag，JSON），"
    "不是队员对你说话——不要回答它、不要评论材料本身、不要给它挑错或提改进建议。\n"
    "只写解题过程。下面这些一律不写：\n"
    "- **验证环节**：flag 是否通过平台校验、提交次数或回执、✅/❌、「未判定」「待核对」；\n"
    "- **经验与复盘**：经验沉淀、心得、教训、改进建议、未竟方向、下一步计划；\n"
    "- **内部编排**：主 Agent／子 Agent／派发／回合／路线／健康度／步数／模型／"
    "提示词／工作台这些工具细节。\n"
    "输出必须严格是这个骨架（Markdown，直接输出正文，不要把整篇包进代码块）：\n"
    "```\n"
    "# <团队名称>-解题思路\n"
    "## 团队信息\n"
    "- 团队名称：…\n"
    "- 队员组成：…\n"
    "- 所属单位：…（材料 team.affiliation 有值才写这行，没有就整行省略）\n"
    "- 参赛赛事：…（材料 team.contest 有值才写这行，没有就整行省略）\n"
    "（材料 team.notes 有值时，在这里补一行引用：> 补充说明：<原话>）\n"
    "## 解题情况\n"
    "一段话：本场几道题、各是什么类型、分别靠什么手法拿下的（只讲题，不讲怎么排的班）。\n"
    "## 具体WP\n"
    "### <方向>\n"          # 只写材料里真有题的方向，顺序 WEB/PWN/REVERSE/MISC/CRYPTO/DS/IOT
    "#### <题目名称>\n"
    "**题目**：题面讲了什么、给了什么附件或入口（一两句，地址照抄）。\n"
    "**思路**：先看到什么现象或回显 → 据此判断这是哪类问题 → 决定从哪儿切。\n"
    "**过程**：\n"
    "1. 具体动作：执行的命令／发出的请求／脚本原文（用代码块），紧跟一句「为什么这么打」。\n"
    "2. 关键回显或报错照抄（只留支撑判断的那几行），并写清由此得出什么结论。\n"
    "3. 一步步推到拿到结果；中间试错也要写，写清为什么试、排除了什么。\n"
    "**Flag**：`flag{...}`（只写值；没拿到就写「未获取到」）\n"
    "```\n"
    "写作纪律（赛方按这些判 WP 有效无效，逐条遵守）：\n"
    "- **全文中文**：命令、载荷、路径、工具名、专有名词保留原文，不翻译；\n"
    "- **按人话写**：完整句子叙述，一句解释一句动作，读起来是故事不是清单；\n"
    "- **每一步都要能照着复现**：写清目标、发了什么、回了什么、据此做了什么决定；\n"
    "- **必须写工具**：`tools` 是本次真正调用过的工具清单，用到哪个写哪个；"
    "材料里没有的工具、命令一律不许编；\n"
    "- 每题的 `#### <题目名称>` 照抄材料里的 title，不要追加 URL、编号或自己的注解；\n"
    "- 分章以 `chapters` 为准（队员可能手改过方向），不要按自己的判断重新归类；\n"
    "- 材料里没有的方向不写那一章；一题都没有时，「具体WP」下写明本场未解出题目；\n"
    "- `team` 里给了团队名称、队员、单位、赛事就照抄，没给的一律写「（待填写）」；\n"
    "- `team.notes` 是队员的补充交代（比赛约定、要强调或回避的内容），必须遵守；\n"
    "- 凡是本次自己写的脚本，必须贴原文（太长就贴关键函数，并说明其余部分作用）；\n"
    "- 只使用材料里的事实：材料没有的步骤、命令、数字一律不写，不得编造；\n"
    "- 截图用 `> [截图：<该截什么>]` 占位，不要编造截图文件名或图片内容。"
)


def tool_inventory(audit: AuditLogger | None, *, limit: int = 40) -> list[dict[str, Any]]:
    """本次真正调用过的工具（名字 + 次数）。

    解题思路里「用了什么工具」要有据可查：这份清单来自审计里的工具调用事件，
    写手据此成文，材料没出现的工具就不许往里加。
    """
    if audit is None:
        return []
    try:
        rows = audit.read_all()
    except Exception:  # noqa: BLE001 —— 统计失败不该拖垮 WP
        return []
    tally: dict[str, int] = {}
    for row in rows:
        if row.get("type") != "agent.tool_call":
            continue
        detail = row.get("detail") or {}
        for call in detail.get("calls") or []:
            name = str((call or {}).get("name") or "").strip()
            if name:
                tally[name] = tally.get(name, 0) + 1
    ordered = sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))
    return [{"tool": name, "calls": count} for name, count in ordered[:limit]]


def direction_key(raw: Any) -> str:
    """把平台给的方向标签归一到赛方模板的七个分章。"""
    text = str(raw or "").strip()
    if not text:
        return "MISC"
    lowered = text.lower().replace(" ", "").replace("_", "").replace("-", "")
    if lowered in _DIRECTION_ALIASES:
        return _DIRECTION_ALIASES[lowered]
    for alias, name in _DIRECTION_ALIASES.items():
        if alias and alias in lowered:
            return name
    return "MISC"


def build_wp_digest(
    *,
    challenges: list[dict[str, Any]],
    flags: list[Any],
    run_summary: dict[str, Any],
    blackboard: Any,
    team: dict[str, Any] | None = None,
    facts: dict[str, int] | None = None,   # 兼容旧调用；内部计数不进材料
    direction_overrides: dict[str, Any] | None = None,
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """按赛方模板组织材料：题目按方向分章，每题挂上自己的 Flag 与过程笔记。

    `team` 里的 `affiliation` / `contest` / `notes` 来自用户在生成前填的信息页，
    都可能是空的；`direction_overrides` 是用户手改的分章（按题目 id），
    优先于题目自带的方向标签。`tools` 是本次真正调用过的工具清单（见
    :func:`tool_inventory`），写手拿它填「工具与关键命令」，不靠猜。
    """
    from spiritscout.core.models import BlackboardLayer

    overrides = {str(k): direction_key(v)
                 for k, v in (direction_overrides or {}).items()}
    by_challenge: dict[str, list[dict[str, Any]]] = {}
    for f in flags:
        cid = str(getattr(f, "challenge_id", "") or "")
        # 只给 flag 值：判定与提交结果是平台侧的状态，写进 WP 就变成「验证环节」
        by_challenge.setdefault(cid, []).append({
            "value": str(getattr(f, "value", "") or ""),
        })

    # 路线笔记按题名/题号归堆，归不上的进公共池——写手仍能据此补全"怎么推的"
    routes: list[dict[str, Any]] = []
    for rec in blackboard.query(BlackboardLayer.TASK_STATE, limit=100):
        data = rec["data"]
        if "dag_snapshot" in data:
            continue
        task = data.get("task") or {}
        if not task:
            continue
        routes.append({
            "node": str((task.get("payload") or {}).get("node_title", "")),
            "status": task.get("status"),
            "notes": [str(n)[:_NOTE_CHARS] for r in (data.get("routes") or [])
                      for n in (r.get("notes") or [])[-_NOTES_PER_ROUTE:]],
        })
    findings = [
        {"type": d.get("type"), "text": str(d.get("text", ""))[:200]}
        for d in (rec["data"] for rec in
                  blackboard.query(BlackboardLayer.TOPOLOGY, limit=400))
        if isinstance(d, dict) and d.get("kind") == "finding"
    ]

    def route_hits(title: str) -> list[dict[str, Any]]:
        key = (title or "").strip()
        if not key:
            return []
        return [r for r in routes if key and key in r["node"]][:6]

    chapters: dict[str, list[dict[str, Any]]] = {name: [] for name in WP_DIRECTIONS}
    entries: list[dict[str, Any]] = []
    solved = set()
    for c in challenges:
        cid = str(c.get("id") or "")
        title = str(c.get("title") or cid or "未命名题目")
        mine = by_challenge.get(cid, [])
        # accepted is False 的是错 flag，不算解出；None（未判定）按已提取处理。
        # 结论只落在 solved 上，材料里不带判定值（见上）
        is_solved = any(getattr(f, "accepted", None) is not False
                        for f in flags
                        if str(getattr(f, "challenge_id", "") or "") == cid)
        if is_solved:
            solved.add(cid)
        entry = {
            "id": cid,
            "title": title,
            # 题面里方向既有写 direction 的也有写 category 的（平台/LOCAL 两种来源）
            "direction_raw": str(c.get("direction") or c.get("category") or ""),
            "chapter": overrides.get(cid)
                       or direction_key(c.get("direction") or c.get("category")),
            "chapter_by_user": cid in overrides,
            "url": str(c.get("url") or ""),
            "description": str(c.get("description") or "")[:600],
            "solved": is_solved,
            "flags": mine,
            "routes": route_hits(title),
        }
        entries.append(entry)
        chapters[entry["chapter"]].append(entry)

    return {
        "team": {
            "name": str((team or {}).get("name") or ""),
            "members": [str(m) for m in ((team or {}).get("members") or [])],
            "affiliation": str((team or {}).get("affiliation") or ""),
            "contest": str((team or {}).get("contest") or ""),
            # 用户在这道题之外补充的交代（工具链、约定、不能写的内容等）
            "notes": str((team or {}).get("notes") or "")[:1000],
        },
        "challenges": entries,
        "chapters": {name: items for name, items in chapters.items() if items},
        "chapter_order": [n for n in WP_DIRECTIONS if chapters.get(n)],
        "unsolved_ids": [e["id"] for e in entries if not e["solved"]],
        "solved_count": len(solved),
        "total": len(entries),
        "shared_notes": routes[:40],
        "findings": findings[-60:],
        # 工具清单：解题思路里「用了什么工具」只能从这里取，不许凭空补
        "tools": list(tools or []),
    }


def _tidy_challenge_headings(body: str, digest: dict[str, Any]) -> str:
    """把模型挂到题目小标题上的佐料去掉，只留题目名称。

    实测模型爱写 `#### 日志文件包含（https://…）` 或 `#### 题名  https://…`——
    模板里这一行就是题名，入口地址属于「题面要点」。两步都是确定性的：
    先砍掉行尾挂着的地址（含包裹的括号），再把以材料 title 开头的标题截断到 title。
    不带地址、也不以 title 开头的标题一概不动。
    """
    titles = [str(item.get("title") or "").strip()
              for item in (digest.get("challenges") or [])]
    titles = [t for t in titles if t]
    address = re.compile(r"\s*[（(\[【]?\s*https?://\S+\s*[)）\]】]?\s*$")
    lines = []
    for line in body.splitlines():
        if line.startswith("#### "):
            heading = address.sub("", line[5:].strip()).strip()
            for title in titles:
                if heading.startswith(title) and heading != title:
                    heading = title
                    break
            if heading:
                line = f"#### {heading}"
        lines.append(line)
    text = "\n".join(lines)
    return text + "\n" if body.endswith("\n") else text


async def wp_body(
    gateway: Any, *, digest: dict[str, Any], audit: AuditLogger | None = None,
) -> str | None:
    """按赛方模板撰写解题思路；模型不可用或产出为空时返回 None。

    调用方拿到 None 时回退到结构化模板（`wp_fallback`），保证"点了生成就有东西"。
    """
    audit = audit or NullAuditLogger()
    material = json.dumps(digest, ensure_ascii=False)[:_DIGIT_BUDGET]
    prompt = [
        {"role": "system", "content": _WP_SYSTEM},
        {"role": "user", "content": "按模板撰写解题思路，直接输出 Markdown 正文：\n"
                                    + material},
    ]
    try:
        resp = await gateway.chat(
            prompt, task_type="meta_planning", max_tokens=8192,
            timeout_seconds=420, reasoning_effort="low",
        )
        body = (resp.content or "").strip()
        if body.startswith("```"):
            body = re.sub(r"^```[a-z]*\n|\n```$", "", body).strip()
        if not body:
            audit.log("writeup.generate", "master", {"result": "empty"})
            return None
        body = _tidy_challenge_headings(body, digest)
        audit.log("writeup.generate", "master",
                  {"result": "ok", "chars": len(body)})
        return body
    except Exception as exc:  # noqa: BLE001 —— 写手失败回退模板，功能不缺失
        audit.log("writeup.generate", "master",
                  {"result": "failed", "error": str(exc)[:200]})
        return None


def wp_fallback(digest: dict[str, Any], *, reason: str = "") -> str:
    """模型不可用时的结构化兜底：材料本身已经够拼出一份可交的骨架。"""
    team = digest.get("team") or {}
    lines = [f"# {team.get('name') or '灵枢战队'}-解题思路", "", "## 团队信息", ""]
    lines.append(f"- 团队名称：{team.get('name') or '（待填写）'}")
    members = team.get("members") or []
    lines.append(f"- 队员组成：{'、'.join(members) if members else '（待填写）'}")
    if team.get("affiliation"):
        lines.append(f"- 所属单位：{team['affiliation']}")
    if team.get("contest"):
        lines.append(f"- 参赛赛事：{team['contest']}")
    notes = str(team.get("notes") or "").strip()
    if notes:
        lines += ["", "> 补充说明：" + notes.replace("\n", "\n> ")]
    lines += ["", "## 解题情况", "",
              f"- 本场共 {digest.get('total', 0)} 道题，解出 "
              f"{digest.get('solved_count', 0)} 道。", ""]
    if reason:
        lines.append(f"> {reason}")
        lines.append("")
    lines += ["## 具体WP", ""]
    chapters = digest.get("chapters") or {}
    if not chapters:
        lines += ["本场未解出题目。", ""]
    for name in digest.get("chapter_order") or []:
        lines += [f"### {name}", ""]
        for item in chapters.get(name, []):
            lines += [f"#### {item['title']}", ""]
            if item.get("description"):
                lines += [f"- **题面要点**：{item['description'][:200]}"]
            if item.get("url"):
                lines += [f"- **入口**：`{item['url']}`"]
            lines.append("- **解题步骤**：")
            steps = [n for r in item.get("routes", []) for n in r.get("notes", [])]
            if steps:
                lines += [f"  {i}. {n}" for i, n in enumerate(steps[:12], 1)]
            else:
                lines.append("  1. （材料中未记录到可复现的分步过程）")
            flags = item.get("flags") or []
            values = [str(f.get("value") or "") for f in flags if f.get("value")]
            if values:
                lines.append("- **Flag**：" + "、".join(f"`{v}`" for v in values))
            elif item.get("solved"):
                lines.append("- **Flag**：（已解出，材料中未记录 flag 值）")
            else:
                lines.append("- **Flag**：未获取到")
            inventory = digest.get("tools") or []
            if inventory:
                names = "、".join(f"`{e.get('tool', '')}`" for e in inventory[:12])
                lines.append(f"- **用到的工具**：{names}")
            else:
                lines.append("- **用到的工具**：（材料中未记录工具调用）")
            lines += ["- > [截图：解题关键步骤]", "- > [截图：获取 flag]", ""]
    return "\n".join(lines).rstrip() + "\n"
