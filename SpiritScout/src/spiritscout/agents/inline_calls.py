"""把模型写在正文里的工具调用接住。

本地小模型（没经过函数调用微调的那一类）经常不按协议返回 ``tool_calls``，而是把
``{"name": ..., "arguments": {...}}`` 当成正文写出来——有时还包在 ```json 或
``<tool_call>`` 里。按协议解析会得到「这一轮没有工具调用」，于是整条路线被判定为
调查结束、直接收尾：实测 Qwen2.5-Coder-7B 8 条路线全部这样死在第 1 回合，一步没走。

这里只做一件事：从正文里认出这种「本意是工具调用」的片段，交还给上层当真正的
工具调用执行。认不准就不认——正文里没有同时出现 name 与 arguments 的 JSON 对象时
原样返回空列表。
"""
from __future__ import annotations

import json
import re
from typing import Any

# 先整块捞出来，再由 _balanced_objects 找顶层对象：工具调用的 arguments 里常带
# 嵌套对象与数组（比如 ask_user 的 options），用 `\{.*?\}` 非贪婪会在第一个 `}`
# 处截断，得到半截 JSON、解析失败——实测这类调用就是这样被整条漏掉的。
_FENCED_BLOCK = re.compile(r"```[a-zA-Z0-9_+-]*\s*(.*?)```", re.S)
_TAGGED_BLOCK = re.compile(
    r"<(?:tool_call|function_call|tool)>\s*(.*?)\s*</(?:tool_call|function_call|tool)>", re.S)
_MARKED_KEYS = ('"name"', "'name'")
# 这些参数的值一旦被输出上限截断，补全后执行的就是「半条命令/半段代码」——
# 与其猜，不如不执行，让下一回合重写一遍。
_CUT_SENSITIVE = frozenset({"command", "code", "flag", "url", "path", "script"})
_LAST_KEY = re.compile(r'"([A-Za-z_][\w-]*)"\s*:\s*$')


def _scan(text: str) -> tuple[list[str], list[str], bool]:
    """返回（平衡的顶层对象, 未闭合的括号栈, 是否停在半截字符串里）。"""
    objects: list[str] = []
    stack: list[str] = []
    start = -1
    in_string = False
    escape = False
    for index, char in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "{[":
            if not stack:
                start = index
            stack.append("}" if char == "{" else "]")
        elif char in "}]" and stack:
            stack.pop()
            if not stack and start >= 0:
                objects.append(text[start:index + 1])
                start = -1
    return objects, stack, in_string


def _balanced_objects(text: str) -> list[str]:
    return _scan(text)[0]


def _close_cut_json(raw: str) -> str:
    """补上被输出上限截断的引号与右括号：补不成合法 JSON 就算了。"""
    objects, stack, in_string = _scan(raw)
    if objects or not stack:
        return ""
    body = raw.strip()
    if not in_string and body.endswith((",", ":")):
        body = body.rstrip().rstrip(",:").rstrip()
    if in_string:
        # 停在半截字符串里：最后一个键名若是命令/代码/flag 这类内容值，补出来也是
        # 半条命令，执行它只会误导——直接放弃，让模型下一回合重写。
        opened = body.rfind('"')
        key_match = _LAST_KEY.search(body[:opened]) if opened > 0 else None
        if key_match and key_match.group(1) in _CUT_SENSITIVE:
            return ""
        body += '"'
    return body + "".join(reversed(stack))


def _as_call(obj: Any, index: int) -> dict[str, Any] | None:
    if not isinstance(obj, dict):
        return None
    function = obj.get("function") if isinstance(obj.get("function"), dict) else {}
    name = obj.get("name") or function.get("name") or obj.get("tool") or obj.get("tool_name")
    if not isinstance(name, str) or not name.strip():
        return None
    args = obj.get("arguments", obj.get("parameters", obj.get("args",
                                                                function.get("arguments"))))
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            args = {}
    if not isinstance(args, dict):
        args = {}
    return {"id": str(obj.get("id") or f"recovered-{index}"),
            "name": name.strip(), "arguments": args,
            "raw": json.dumps(args, ensure_ascii=False), "recovered": True}


def _candidates(text: str) -> list[str]:
    out: list[str] = []
    for block in _TAGGED_BLOCK.findall(text) + _FENCED_BLOCK.findall(text):
        found = _balanced_objects(block)
        if found:
            out.extend(found)
        else:
            repaired = _close_cut_json(block)
            if repaired:
                out.append(repaired)
    if out:
        return out
    found = _balanced_objects(text)
    if found:
        return found
    # 正文尾部就是半截 JSON（输出额度用完，连 ``` 都没闭上）
    tail = text.rsplit("```", 1)[-1] if "```" in text else text
    tail = tail.strip()
    if tail and not tail.startswith("{"):
        head, _, rest = tail.partition("\n")
        if rest and head.strip().isalnum():   # 去掉代码块的语言标识行
            tail = rest.strip()
    if tail.startswith("{"):
        repaired = _close_cut_json(tail)
        if repaired:
            return [repaired]
    return []


def recover_inline_tool_calls(content: str) -> list[dict[str, Any]]:
    """从正文里恢复工具调用；没有可信片段时返回空列表。"""
    text = content or ""
    if not text or not any(mark in text for mark in _MARKED_KEYS):
        return []
    calls: list[dict[str, Any]] = []
    for raw in _candidates(text):
        try:
            obj = json.loads(raw)
        except ValueError:
            continue
        call = _as_call(obj, len(calls))
        if call is not None:
            calls.append(call)
    return calls
