#!/usr/bin/env python
"""核对本地 LLM 端点：连不连得上、配置里的模型 id 对不对。

本地模型最常见的两个坑都不在代码里——服务没启动，或者填的模型名和端点
实际返回的对不上（LM Studio 会把目录名的 ``-GGUF`` 后缀去掉并转小写）。
这个脚本一次把两件事都问清楚，只在控制台打印结论，不改任何配置。

用法::

    python scripts/check_local_llm.py                 # 查配置里第一个本地供应商
    python scripts/check_local_llm.py --provider 本地  # 指定供应商名
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from spiritscout.config.settings import (  # noqa: E402 —— 需要先改 sys.path
    load_model_config,
)


def _local_providers() -> dict[str, tuple[str, str]]:
    """从模型配置里挑出指向本机的供应商：{名字: (base_url, api_key)}。"""
    from spiritscout.config.settings import ModelConfigFile, _load_yaml

    raw = _load_yaml(ROOT / "configs" / "models.yaml")
    cfg = ModelConfigFile.model_validate(raw)
    out: dict[str, tuple[str, str]] = {}
    for provider in cfg.providers:
        host = provider.base_url.lower()
        if any(token in host for token in ("127.0.0.1", "localhost", "0.0.0.0", "::1")):
            out[provider.name] = (provider.base_url, provider.api_key)
    return out


def _probe(base_url: str, api_key: str) -> tuple[bool, object]:
    url = base_url.rstrip("/") + "/models"
    request = urllib.request.Request(url)
    if api_key:
        request.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(request, timeout=6) as response:
            return True, json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}（{url}）"
    except urllib.error.URLError as exc:
        return False, f"连不上 {url} —— {exc.reason}"
    except (TimeoutError, json.JSONDecodeError) as exc:
        return False, f"{type(exc).__name__}: {exc}"


def main() -> int:
    parser = argparse.ArgumentParser(description="核对本地 LLM 端点与模型 id")
    parser.add_argument("--provider", help="供应商名（默认查第一个指向本机的）")
    args = parser.parse_args()

    providers = _local_providers()
    if not providers:
        print("配置里没有指向本机的供应商（看 configs/models.yaml 的 providers）。")
        return 1

    name = args.provider or next(iter(providers))
    if name not in providers:
        print(f"没有名为 {name!r} 的本地供应商。可用的：{', '.join(providers)}")
        return 1

    base_url, api_key = providers[name]
    print(f"供应商 {name}  base_url={base_url}")
    ok, payload = _probe(base_url, api_key)
    if not ok:
        print(f"  探测失败：{payload}")
        print("  → 本地服务通常要手动开：LM Studio 进 Developer 页点 Start Server；"
              "Ollama 跑 `ollama serve`。")
        return 1

    served = [item.get("id") for item in (payload or {}).get("data", []) if item.get("id")]
    print(f"  端点可用，对外提供 {len(served)} 个模型：")
    for model_id in served:
        print(f"    {model_id}")
    if not served:
        print("    （空列表：模型还没加载）")
        return 1

    configured = [entry.model for entry in load_model_config(ROOT / "configs" / "models.yaml")
                  if entry.base_url == base_url]
    print("\n配置里指向这个端点的模型：")
    missing = []
    for model_id in configured:
        matched = model_id in served
        print(f"  {'✓' if matched else '✗'} {model_id}")
        if not matched:
            missing.append(model_id)

    if missing:
        print("\n对不上的模型名。端点实际提供的 id 里，与配置最接近的是：")
        for model_id in missing:
            stem = model_id.split("/")[-1].lower().replace("-gguf", "")
            near = [s for s in served if stem in s.lower().replace("-gguf", "")]
            print(f"  {model_id} → {near or served}")
        print("把配置里的 model 改成上面列出的 id 即可（大小写、后缀都要一致）。")
        return 2

    print("\n全部匹配，可以直接用。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
