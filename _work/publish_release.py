#!/usr/bin/env python
"""发布 0.24.2 到 GitHub：push + 创建 Release + 上传资产。

为什么是 Python 而不是 curl/gh：这台机器的 Windows Schannel 坏了
（AcquireCredentialsHandle 返回 SEC_E_NO_CREDENTIALS），curl 和 git 的
https 传输都会挂。Python 的 urllib 走 OpenSSL，实测能连 api.github.com，
所以 API 调用和资产上传都交给它；push 那一步仍走 git，但需要
GIT_SSL_NO_VERIFY=1 绕过本地证书链问题。

用法：
    $env:GH_TOKEN = 'ghp_...'
    python _work/publish_release.py

token 只从环境变量读，不落盘、不进命令行参数（避免出现在进程列表里）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = "qzuser/auto-target-range-v2"
TAG = "v0.24.2"
TITLE = "0.24.2 — CTF 不再拦输入、附件清空修复、打包说明"
ROOT = Path(__file__).resolve().parent.parent
PACKAGES = ROOT / "packages"
NOTES = ROOT / "_work" / "release_notes_0.24.2.md"

ASSETS = [
    PACKAGES / "SpiritScout-0.24.2-portable.zip",
    PACKAGES / "spiritscout-0.24.2-py3-none-any.whl",
    PACKAGES / "spiritscout-0.24.2.tar.gz",
]

API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"


def token() -> str:
    value = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
    value = value.strip()
    if not value:
        sys.exit("缺少凭证：先设 $env:GH_TOKEN = 'ghp_...'（需要 repo 权限）")
    return value


def call(
    method: str,
    url: str,
    token_value: str,
    payload: dict | None = None,
    *,
    raw: bytes | None = None,
    content_type: str = "application/json",
    timeout: int = 120,
) -> tuple[int, dict]:
    """发一个 API 请求，返回 (状态码, 解析后的 JSON)。"""
    if raw is not None:
        data, ctype = raw, content_type
    elif payload is not None:
        data, ctype = json.dumps(payload).encode("utf-8"), "application/json"
    else:
        data, ctype = None, None

    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Authorization", f"Bearer {token_value}")
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("X-GitHub-Api-Version", "2022-11-28")
    request.add_header("User-Agent", "spiritscout-release")
    if ctype:
        request.add_header("Content-Type", ctype)

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
            return response.status, (json.loads(body) if body.strip() else {})
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        try:
            detail = json.loads(body)
        except json.JSONDecodeError:
            detail = {"raw": body[:400]}
        return exc.code, detail


def push(token_value: str) -> bool:
    """用 token 推到 origin/main。本地 Schannel 坏，必须关证书校验。"""
    print("→ 推送 main")
    url = f"https://x-access-token:{token_value}@github.com/{REPO}.git"
    env = {**os.environ, "GIT_SSL_NO_VERIFY": "1", "GIT_TERMINAL_PROMPT": "0"}
    result = subprocess.run(
        ["git", "-c", "credential.helper=", "push", url, "main:main"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env,
        timeout=600,
        check=False,
    )
    output = (result.stdout + result.stderr).strip()
    # 输出里可能带 token，替换掉再打印
    print("  " + output.replace(token_value, "***").replace("\n", "\n  ")[:1200])
    return result.returncode == 0


def ensure_release(token_value: str) -> dict:
    """创建 Release；已存在就复用。"""
    notes = NOTES.read_text(encoding="utf-8") if NOTES.exists() else f"Release {TAG}"
    print(f"→ 创建 Release {TAG}")
    status, data = call(
        "POST",
        f"{API}/repos/{REPO}/releases",
        token_value,
        {
            "tag_name": TAG,
            "target_commitish": "main",
            "name": TITLE,
            "body": notes,
            "draft": False,
            "prerelease": False,
        },
    )
    if status == 201:
        print(f"  已创建: {data.get('html_url')}")
        return data
    if status == 422:
        print("  Release 已存在，复用现有记录")
        status, data = call("GET", f"{API}/repos/{REPO}/releases/tags/{TAG}", token_value)
        if status == 200:
            print(f"  已存在: {data.get('html_url')}")
            return data
    sys.exit(f"  创建失败：HTTP {status} {json.dumps(data, ensure_ascii=False)[:500]}")


def existing_assets(token_value: str, release_id: int) -> set[str]:
    status, data = call("GET", f"{API}/repos/{REPO}/releases/{release_id}/assets", token_value)
    if status != 200:
        return set()
    items = data if isinstance(data, list) else data.get("assets", [])
    return {item.get("name", "") for item in items}


def upload(token_value: str, release: dict) -> None:
    """逐个上传资产。已有同名资产先删掉，便于重跑。"""
    release_id = release.get("id")
    present = existing_assets(token_value, release_id) if release_id else set()

    for path in ASSETS:
        if not path.exists():
            print(f"  ⚠ 缺少资产：{path.name}")
            continue
        if path.name in present:
            print(f"  删除同名旧资产 {path.name}")
            _status, data = call(
                "GET", f"{API}/repos/{REPO}/releases/{release_id}/assets", token_value
            )
            items = data if isinstance(data, list) else data.get("assets", [])
            for item in items:
                if item.get("name") == path.name:
                    call("DELETE", f"{API}/repos/{REPO}/releases/assets/{item['id']}", token_value)
                    break

        size_mb = path.stat().st_size / (1024 * 1024)
        print(f"→ 上传 {path.name}（{size_mb:.1f} MB）")
        # 229 MB 的 zip 不能整读进内存：把文件对象交给 urllib，它按块读并
        # 自己算 Content-Length（文件对象支持 len() 时会用 fstat 的 st_size）。
        content_type = "application/zip" if path.suffix == ".zip" else "application/octet-stream"
        url = f"{UPLOADS}/repos/{REPO}/releases/{release_id}/assets?name={path.name}"
        with path.open("rb") as handle:
            request = urllib.request.Request(url, data=handle, method="POST")
            request.add_header("Authorization", f"Bearer {token_value}")
            request.add_header("Content-Type", content_type)
            request.add_header("Content-Length", str(path.stat().st_size))
            request.add_header("User-Agent", "spiritscout-release")
            try:
                with urllib.request.urlopen(request, timeout=1800) as response:
                    body = json.loads(response.read().decode("utf-8", "replace") or "{}")
                    print(f"  完成: {body.get('browser_download_url', '?')}")
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")
                print(f"  ✗ 上传失败 HTTP {exc.code}: {detail[:300]}")


def main() -> None:
    value = token()
    if not push(value):
        sys.exit("推送失败，后面的步骤不再执行")
    release = ensure_release(value)
    upload(value, release)
    print("\n全部完成:", release.get("html_url", ""))


if __name__ == "__main__":
    main()
