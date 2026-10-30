"""模型与供应商管理路由。

第三刀：模型页背后的全部增删改查（供应商 CRUD、密钥入库、拉取模型列表、
模型画像、命名降级链、连通性测试）。这一组只碰 `configs/models.yaml`、
`configs/agent_models.yaml` 与本机密钥库，和会话执行链没有交集，
正好整块搬出 `create_app`。

两条约定原样保留：
- 读 API 只回规范公开字段，密钥与历史污染字段永不外泄；
- 命名链路由必须先于 `/api/models/{model:path}` 注册，否则 `naming`
  会被当成模型 ID 吞进动态路由。
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException

from spiritscout.config.settings import GatewayConfig, ModelEntry, SystemConfig
from spiritscout.core.audit import AuditLogger
from spiritscout.core.exceptions import SpiritScoutError
from spiritscout.web import agentcfg, modelcfg, vault

# 模型条目的公开字段 = 注册表声明的全部字段去掉 api_key
_MODEL_PUBLIC_FIELDS = tuple(k for k in ModelEntry.model_fields if k != "api_key")
_PROVIDER_PUBLIC_FIELDS = ("name", "provider", "base_url", "api_format")


def mount_models(app: FastAPI, *, cfg: SystemConfig) -> None:
    """挂模型与供应商管理路由。"""

    def _providers_view() -> dict[str, Any]:
        providers = modelcfg.read_providers(cfg.models_config_path)
        # 读 API 只回规范公开字段（+密钥状态）：不回吐 YAML 原始键
        return {"path": cfg.models_config_path,
                "providers": [{**{k: p.get(k) for k in _PROVIDER_PUBLIC_FIELDS},
                               **vault.key_status(p, str(p.get("name") or ""))}
                              for p in providers]}

    def _models_view(entries: list[dict[str, Any]]) -> dict[str, Any]:
        # 读 API 只回规范公开字段：密钥字段与历史污染字段不再扩散。
        # enabled 缺省即启用（YAML 里只在停用时留一行），这里补回确定值，
        # 免得前端拿到 null 还要自己猜缺省语义。
        return {"path": cfg.models_config_path,
                "models": [{**{k: e.get(k) for k in _MODEL_PUBLIC_FIELDS},
                            "enabled": e.get("enabled", True)}
                           for e in entries]}

    def _model_error(exc: SpiritScoutError) -> HTTPException:
        msg = str(exc)
        status = 409 if "已存在" in msg else 404 if "不存在" in msg else 422
        return HTTPException(status, msg)

    def _pop_key_value(payload: dict[str, Any]) -> str | None:
        """摘出 api_key_value（G8：绝不进 YAML、不回传、留痕不含值）。

        返回 None=请求未提供密钥字段（保持既有密钥不动）；空串=清除语义。
        密钥属于供应商：同一端点下的模型共用一条记录。
        """
        if "api_key_value" not in payload:
            return None
        return str(payload.pop("api_key_value") or "").strip()

    def _store_key(provider: str, value: str) -> None:
        vault.set_key(provider, value)             # 空串 = 清除
        AuditLogger(cfg.audit_log_path).log(
            "system.lifecycle", "modelcfg",
            {"action": "model_key_set" if value else "model_key_cleared",
             "provider": provider, "source": "vault"})

    @app.get("/api/providers")
    async def list_providers() -> dict[str, Any]:
        return _providers_view()

    @app.get("/api/provider-presets")
    async def provider_presets() -> dict[str, Any]:
        """厂商预设目录（添加供应商对话框：选中带入协议与地址）。"""
        from spiritscout.web.provider_api import PROVIDER_PRESETS
        return {"presets": PROVIDER_PRESETS}

    @app.post("/api/providers", status_code=201)
    async def add_provider(payload: dict[str, Any]) -> dict[str, Any]:
        payload = dict(payload)
        key_value = _pop_key_value(payload)
        try:
            payload = modelcfg.canonical_provider(payload)
            modelcfg.upsert_provider(cfg.models_config_path, payload)
        except SpiritScoutError as exc:
            raise _model_error(exc) from exc
        if key_value is not None:                  # 校验通过才动密钥库
            _store_key(str(payload.get("name") or ""), key_value)
        return _providers_view()

    @app.put("/api/providers/{name}")
    async def update_provider(name: str, payload: dict[str, Any]) -> dict[str, Any]:
        """供应商更新：先完整校验落盘（失败不动密钥库——已有可用密钥不因
        失败请求改变），再做密钥操作。语义：仅改名=密钥随名迁移；
        改名+新密钥=迁移后按显式输入覆写；api_key_value 空串=清除。"""
        payload = dict(payload)
        key_value = _pop_key_value(payload)
        try:
            payload = modelcfg.canonical_provider({**payload, "name": payload.get("name", name)})
            new_name = payload["name"]
            modelcfg.upsert_provider(cfg.models_config_path, payload,
                                     original_name=name)
        except SpiritScoutError as exc:
            raise _model_error(exc) from exc
        if new_name != name:
            vault.rename_key(name, new_name)       # 先迁移
        if key_value is not None:
            _store_key(new_name, key_value)        # 再按显式输入覆写/清除
        return _providers_view()

    @app.delete("/api/providers/{name}")
    async def delete_provider(name: str) -> dict[str, Any]:
        try:
            modelcfg.delete_provider(cfg.models_config_path, name)
        except SpiritScoutError as exc:
            raise _model_error(exc) from exc
        vault.drop_key(name)
        return _providers_view()

    @app.post("/api/providers/{name}/models")
    async def fetch_provider_models(name: str, payload: dict[str, Any]) -> dict[str, Any]:
        """从供应商端点拉取可用模型列表（用户点击触发；未保存的编辑也可先拉）。

        端点没有实现模型列表接口是常态——失败时如实回报试过的地址与错误，
        用户改用手动填模型 ID（同一入口）。
        """
        from spiritscout.web.provider_api import fetch_model_list

        providers = {str(p.get("name")): p for p in
                     modelcfg.read_providers(cfg.models_config_path)}
        stored = providers.get(name, {})
        payload = dict(payload or {})
        key_value = str(payload.pop("api_key_value", "") or "").strip()
        spec = {
            "name": name,
            "provider": str(payload.get("provider") or stored.get("provider")
                            or "openai_compatible"),
            "base_url": str(payload.get("base_url") or stored.get("base_url") or ""),
            # 密钥只认本次直填或密钥库——YAML 不落密钥，stored 里没有可用值
            "api_key": key_value or vault.get_key(name),
        }
        result = await fetch_model_list(spec)
        AuditLogger(cfg.audit_log_path).log("system.lifecycle", "modelcfg", {
            "action": "provider_model_list", "provider": name,
            "ok": result.get("ok"), "count": len(result.get("models") or []),
            "error": str(result.get("error", ""))[:200]})
        return result

    @app.post("/api/models/batch", status_code=201)
    async def add_models_batch(payload: dict[str, Any]) -> dict[str, Any]:
        """批量启用供应商下的模型（从拉取的列表里勾选）。"""
        provider_ref = str(payload.get("provider_ref") or "")
        ids = [str(x) for x in (payload.get("models") or []) if str(x).strip()]
        try:
            entries, added = modelcfg.add_entries(
                cfg.models_config_path, provider_ref, ids)
        except SpiritScoutError as exc:
            raise _model_error(exc) from exc
        return {**_models_view(entries), "added": added}

    @app.get("/api/models")
    async def list_models() -> dict[str, Any]:
        return _models_view(modelcfg.read_entries(cfg.models_config_path))

    # 命名链路由须先于 /api/models/{model:path} 注册（静态段优先匹配），
    # 否则 "naming" 会被当作模型 ID 吞进动态路由。
    @app.get("/api/models/naming")
    async def naming_chain_view() -> dict[str, Any]:
        """会话命名候选链（「模型」页维护的降级顺序；空 = 跟随灵枢指派）。"""
        try:
            chain = agentcfg.read_naming_chain(cfg.agent_models_path)
        except (SpiritScoutError, OSError) as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"chain": chain, "path": cfg.agent_models_path}

    @app.put("/api/models/naming")
    async def set_naming_chain(payload: dict[str, Any]) -> dict[str, Any]:
        """整链写回：顺序即降级顺序，由用户在页面排定，后端只校验存在性。"""
        from spiritscout.config import load_model_config
        raw = payload.get("models")
        if not isinstance(raw, list):
            raise HTTPException(422, "models 必须是模型 ID 数组")
        valid = {m.model for m in load_model_config(cfg.models_config_path)}
        try:
            chain = agentcfg.set_naming_chain(
                cfg.agent_models_path, [str(x) for x in raw], valid)
        except SpiritScoutError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"chain": chain, "path": cfg.agent_models_path}

    @app.post("/api/models", status_code=201)
    async def add_model(payload: dict[str, Any]) -> dict[str, Any]:
        """手动添加单个模型（自动拉取失败或列表里没有时的入口）。"""
        payload = dict(payload)
        try:
            entries = modelcfg.upsert_entry(cfg.models_config_path, payload)
        except SpiritScoutError as exc:
            raise _model_error(exc) from exc
        return _models_view(entries)

    @app.put("/api/models/{model:path}")
    async def update_model(model: str, payload: dict[str, Any]) -> dict[str, Any]:
        """更新模型画像。模型 ID 含 /（org/model）——path 转换器整体捕获，
        %2F 与裸 / 同样命中；/api/models/test 等静态路由不受影响。"""
        payload = dict(payload)
        try:
            entries = modelcfg.upsert_entry(
                cfg.models_config_path, payload, original_model=model,
                assignments_path=cfg.agent_models_path)
        except SpiritScoutError as exc:
            raise _model_error(exc) from exc
        return _models_view(entries)

    @app.patch("/api/models/{model:path}")
    async def set_model_enabled(model: str, payload: dict[str, Any]) -> dict[str, Any]:
        """停用 / 启用某个模型：只翻状态位，不动画像。

        停用后它从编队候选、命名链和路由挑选里一并消失，但配置还在——想临时
        避开某家额度或先放着以后用，不用删掉再重配一遍。要改画像走 PUT。
        """
        if "enabled" not in payload:
            raise HTTPException(422, "只接受 enabled 字段；改画像请用 PUT")
        try:
            entries = modelcfg.set_enabled(
                cfg.models_config_path, model, bool(payload.get("enabled")))
        except SpiritScoutError as exc:
            raise _model_error(exc) from exc
        AuditLogger(cfg.audit_log_path).log("system.lifecycle", "modelcfg", {
            "action": "model_enable" if payload.get("enabled") else "model_disable",
            "model": model})
        return _models_view(entries)

    @app.delete("/api/models/{model:path}")
    async def delete_model(model: str) -> dict[str, Any]:
        try:
            entries = modelcfg.delete_entry(
                cfg.models_config_path, model,
                assignments_path=cfg.agent_models_path)
        except SpiritScoutError as exc:
            raise _model_error(exc) from exc
        return _models_view(entries)

    @app.post("/api/models/test")
    async def test_model(payload: dict[str, Any]) -> dict[str, Any]:
        """连通性测试（用户显式触发的真实外呼；审计留痕 model.call）。"""
        from spiritscout.config import load_model_config
        from spiritscout.gateway import ModelGateway, ModelRegistry

        model = str(payload.get("model") or "")
        # 连通性测试要能看到停用的模型：先测通再启用是正常操作顺序
        entries = vault.apply_keys(
            load_model_config(cfg.models_config_path, include_disabled=True))
        entry = next((e for e in entries if e.model == model), None)
        if entry is None:
            raise HTTPException(404, f"模型不存在: {model}")
        if not entry.api_key:
            return {"ok": False,
                    "error": "密钥未配置——在该模型所属供应商里填入密钥"
                             "（加密存入本机密钥库）"}
        gateway = ModelGateway(
            ModelRegistry(entries),
            GatewayConfig(request_timeout_seconds=25),
            audit=AuditLogger(cfg.audit_log_path))
        try:
            resp = await gateway.chat(
                [{"role": "user", "content": "连通性测试：请只回复 ok"}],
                model=model, max_tokens=16,
                reasoning_effort=str(payload.get("reasoning_effort") or ""))
            return {"ok": True, "latency_ms": round(resp.latency_ms),
                    "sample": resp.content[:80],
                    "has_reasoning": bool(resp.reasoning)}
        except Exception as exc:  # noqa: BLE001 —— 测试结果原样上报告知用户
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
