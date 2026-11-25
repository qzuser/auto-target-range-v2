package com.spiritscout.desktop.state

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.spiritscout.desktop.model.array
import com.spiritscout.desktop.model.boolean
import com.spiritscout.desktop.model.double
import com.spiritscout.desktop.model.element
import com.spiritscout.desktop.model.int
import com.spiritscout.desktop.model.objectOrEmpty
import com.spiritscout.desktop.model.string
import com.spiritscout.desktop.service.SpiritApi
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.net.URLEncoder
import java.nio.charset.StandardCharsets

data class ProviderItem(
    val name: String,
    val provider: String,
    val baseUrl: String,
    val keyConfigured: Boolean,
    val keySource: String,
    val authMethod: String,
    val authStatus: String,
    val rawJson: String
)

data class ModelItem(
    val key: String,
    val model: String,
    val providerRef: String,
    val contextWindow: Long,
    val maxOutputTokens: Long,
    val capabilities: List<String>,
    val reasoningEfforts: List<String>,
    val promptCaching: String,
    val costInputPerMtok: Double,
    val costOutputPerMtok: Double,
    val costCachedInputPerMtok: Double?,
    val costCacheWritePerMtok: Double?,
    val rateLimitRpm: Int,
    val maxConcurrency: Int,
    val qualityScore: Double?,
    val fallbackFor: List<String>,
    val rawJson: String
)

data class ProviderPreset(
    val key: String,
    val name: String,
    val familyName: String,
    val edition: String,
    val provider: String,
    val baseUrl: String
)

class ModelProviderController(
    private val apiProvider: () -> SpiritApi?,
    private val scope: CoroutineScope
) {
    private val prettyJson = Json { prettyPrint = true }
    val providers = mutableStateListOf<ProviderItem>()
    val models = mutableStateListOf<ModelItem>()
    val presets = mutableStateListOf<ProviderPreset>()
    val namingChain = mutableStateListOf<String>()
    val fetchedModels = mutableStateListOf<String>()
    var loading by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set
    var actionMessage by mutableStateOf("")
        private set
    var actionBusy by mutableStateOf(false)
        private set
    var quota by mutableStateOf<JsonElement?>(null)
        private set
    var oauthFlow by mutableStateOf<JsonElement?>(null)
        private set

    fun open() {
        val currentApi = apiProvider() ?: return
        scope.launch {
            loading = true
            error = null
            try {
                val (providerRoot, modelRoot, presetRoot, namingRoot) = coroutineScope {
                    val providers = async { currentApi.get("/api/providers") }
                    val models = async { currentApi.get("/api/models") }
                    val presets = async {
                        runCatching { currentApi.get("/api/provider-presets") }.getOrNull()
                    }
                    val naming = async {
                        runCatching { currentApi.get("/api/models/naming") }.getOrNull()
                    }
                    listOf(providers.await(), models.await(), presets.await(), naming.await())
                }.let { values ->
                    Quad(
                        values[0] ?: Json.parseToJsonElement("{}"),
                        values[1] ?: Json.parseToJsonElement("{}"),
                        values[2],
                        values[3]
                    )
                }
                providers.clear()
                providers += providerRoot.array("providers").map { raw ->
                    val item = raw.objectOrEmpty()
                    ProviderItem(
                        name = item.string("name"),
                        provider = item.string("provider"),
                        baseUrl = item.string("base_url"),
                        keyConfigured = item.boolean("key_configured"),
                        keySource = item.string("key_source"),
                        authMethod = item.string("auth_method"),
                        authStatus = item.string("auth_status"),
                        rawJson = prettyJson.encodeToString(JsonElement.serializer(), raw)
                    )
                }
                models.clear()
                models += modelRoot.array("models").map { raw ->
                    val item = raw.objectOrEmpty()
                    ModelItem(
                        key = item.string("key").ifBlank { item.string("model") },
                        model = item.string("model"),
                        providerRef = item.string("provider_ref").ifBlank { item.string("provider") },
                        contextWindow = item.element("context_window")?.toString()?.toLongOrNull() ?: 0,
                        maxOutputTokens = item.element("max_output_tokens")?.toString()?.toLongOrNull() ?: 0,
                        capabilities = item.array("capabilities").map { it.toString().trim('"') },
                        reasoningEfforts = item.array("reasoning_effort_levels").map { it.toString().trim('"') },
                        promptCaching = item.string("prompt_caching"),
                        costInputPerMtok = item.element("cost_input_per_mtok")?.toString()?.toDoubleOrNull() ?: 0.0,
                        costOutputPerMtok = item.element("cost_output_per_mtok")?.toString()?.toDoubleOrNull() ?: 0.0,
                        costCachedInputPerMtok = item.element("cost_cached_input_per_mtok")?.toString()?.toDoubleOrNull(),
                        costCacheWritePerMtok = item.element("cost_cache_write_per_mtok")?.toString()?.toDoubleOrNull(),
                        rateLimitRpm = item.int("rate_limit_rpm").takeIf { it > 0 } ?: 60,
                        maxConcurrency = item.int("max_concurrency"),
                        qualityScore = item.element("quality_score")?.toString()?.toDoubleOrNull(),
                        fallbackFor = item.array("is_fallback_for").map { it.toString().trim('"') },
                        rawJson = prettyJson.encodeToString(JsonElement.serializer(), raw)
                    )
                }
                presets.clear()
                presets += presetRoot?.array("presets").orEmpty().map { raw ->
                    val item = raw.objectOrEmpty()
                    ProviderPreset(
                        key = item.string("key"),
                        name = item.string("name"),
                        familyName = item.string("family_name"),
                        edition = item.string("edition"),
                        provider = item.string("provider"),
                        baseUrl = item.string("base_url")
                    )
                }
                namingChain.clear()
                namingChain += namingRoot?.array("chain").orEmpty().map { it.toString().trim('"') }
            } catch (failure: Exception) {
                error = failure.message ?: "模型与供应商读取失败"
            } finally {
                loading = false
            }
        }
    }

    fun saveProvider(
        originalName: String?,
        name: String,
        protocol: String,
        baseUrl: String,
        apiKey: String
    ) {
        val currentApi = apiProvider() ?: return
        if (name.isBlank()) {
            error = "供应商名称不能为空。"
            return
        }
        scope.launch {
            actionBusy = true
            error = null
            try {
                val payload = buildJsonObject {
                    put("name", name.trim())
                    put("provider", protocol)
                    put("base_url", baseUrl.trim())
                    if (apiKey.isNotBlank()) put("api_key_value", apiKey.trim())
                }
                if (originalName == null) {
                    currentApi.post("/api/providers", payload.toString())
                } else {
                    currentApi.put("/api/providers/${enc(originalName)}", payload.toString())
                }
                actionMessage = "供应商已保存"
                open()
            } catch (failure: Exception) {
                error = failure.message ?: "供应商保存失败"
            } finally {
                actionBusy = false
            }
        }
    }

    fun deleteProvider(name: String) {
        val currentApi = apiProvider() ?: return
        scope.launch {
            actionBusy = true
            error = null
            try {
                currentApi.delete("/api/providers/${enc(name)}")
                open()
            } catch (failure: Exception) {
                error = failure.message ?: "供应商删除失败"
            } finally {
                actionBusy = false
            }
        }
    }

    fun fetchProviderModels(
        providerName: String,
        protocol: String,
        baseUrl: String,
        apiKey: String = ""
    ) {
        val currentApi = apiProvider() ?: return
        scope.launch {
            actionBusy = true
            error = null
            fetchedModels.clear()
            try {
                val payload = buildJsonObject {
                    put("provider", protocol)
                    put("base_url", baseUrl.trim())
                    if (apiKey.isNotBlank()) put("api_key_value", apiKey.trim())
                }
                val root = currentApi.post(
                    "/api/providers/${enc(providerName)}/models",
                    payload.toString()
                ).objectOrEmpty()
                fetchedModels += root.array("models").mapNotNull { raw ->
                    val item = raw.objectOrEmpty()
                    item.string("id").ifBlank { raw.toString().trim('"') }.takeIf(String::isNotBlank)
                }
                actionMessage = if (root.boolean("ok")) {
                    "已读取 ${fetchedModels.size} 个模型"
                } else {
                    root.string("error").ifBlank { "端点未返回模型列表" }
                }
            } catch (failure: Exception) {
                error = failure.message ?: "模型列表读取失败"
            } finally {
                actionBusy = false
            }
        }
    }

    fun addFetchedModels(providerRef: String, selectedIds: List<String>) {
        val currentApi = apiProvider() ?: return
        if (selectedIds.isEmpty()) return
        scope.launch {
            actionBusy = true
            error = null
            try {
                currentApi.post(
                    "/api/models/batch",
                    buildJsonObject {
                        put("provider_ref", providerRef)
                        put("models", JsonArray(selectedIds.map(::JsonPrimitive)))
                    }.toString()
                )
                fetchedModels.clear()
                open()
            } catch (failure: Exception) {
                error = failure.message ?: "模型批量启用失败"
            } finally {
                actionBusy = false
            }
        }
    }

    fun saveModel(
        originalKey: String?,
        model: String,
        providerRef: String,
        contextWindow: Long,
        maxOutputTokens: Long = 0,
        capabilities: List<String>,
        reasoningEfforts: List<String>,
        promptCaching: String,
        costInputPerMtok: Double = 0.0,
        costOutputPerMtok: Double = 0.0,
        costCachedInputPerMtok: Double? = null,
        costCacheWritePerMtok: Double? = null,
        rateLimitRpm: Int = 60,
        maxConcurrency: Int = 0,
        qualityScore: Double = 1.0,
        fallbackFor: List<String> = emptyList()
    ) {
        val currentApi = apiProvider() ?: return
        if (model.isBlank() || providerRef.isBlank()) {
            error = "模型 ID 和供应商不能为空。"
            return
        }
        scope.launch {
            actionBusy = true
            error = null
            try {
                val existing = models.firstOrNull { it.key == originalKey }
                val payload = buildJsonObject {
                    if (existing != null) put("model", model.trim())
                    else put("model", model.trim())
                    put("provider_ref", providerRef)
                    put("context_window", contextWindow.coerceAtLeast(0))
                    put("max_output_tokens", maxOutputTokens.coerceAtLeast(0))
                    put("capabilities", JsonArray(capabilities.map(::JsonPrimitive)))
                    put("reasoning_effort_levels", JsonArray(reasoningEfforts.map(::JsonPrimitive)))
                    put("prompt_caching", promptCaching.ifBlank { "provider_default" })
                    put("cost_input_per_mtok", costInputPerMtok.coerceAtLeast(0.0))
                    put("cost_output_per_mtok", costOutputPerMtok.coerceAtLeast(0.0))
                    costCachedInputPerMtok?.let { put("cost_cached_input_per_mtok", it.coerceAtLeast(0.0)) }
                    costCacheWritePerMtok?.let { put("cost_cache_write_per_mtok", it.coerceAtLeast(0.0)) }
                    put("rate_limit_rpm", rateLimitRpm.coerceAtLeast(1))
                    put("max_concurrency", maxConcurrency.coerceAtLeast(0))
                    put("quality_score", qualityScore.coerceAtLeast(0.0))
                    put("is_fallback_for", JsonArray(fallbackFor.map(::JsonPrimitive)))
                }
                if (originalKey == null) {
                    currentApi.post("/api/models", payload.toString())
                } else {
                    currentApi.put("/api/models/${enc(originalKey)}", payload.toString())
                }
                open()
            } catch (failure: Exception) {
                error = failure.message ?: "模型保存失败"
            } finally {
                actionBusy = false
            }
        }
    }

    fun deleteModel(key: String) {
        val currentApi = apiProvider() ?: return
        scope.launch {
            actionBusy = true
            try {
                currentApi.delete("/api/models/${enc(key)}")
                open()
            } catch (failure: Exception) {
                error = failure.message ?: "模型删除失败"
            } finally {
                actionBusy = false
            }
        }
    }

    fun testModel(key: String) {
        val currentApi = apiProvider() ?: return
        scope.launch {
            actionBusy = true
            try {
                val result = currentApi.post(
                    "/api/models/test",
                    buildJsonObject { put("model", key) }.toString()
                ).objectOrEmpty()
                actionMessage = if (result.boolean("ok")) {
                    listOf(
                        "连通正常",
                        "${result.int("latency_ms")}ms",
                        result.string("note"),
                        result.string("sample")
                    ).filter(String::isNotBlank).joinToString(" · ")
                } else {
                    result.string("error").ifBlank { "模型测试失败" }
                }
            } catch (failure: Exception) {
                error = failure.message ?: "模型测试失败"
            } finally {
                actionBusy = false
            }
        }
    }

    fun saveNamingChain(modelKeys: List<String>) {
        val currentApi = apiProvider() ?: return
        scope.launch {
            actionBusy = true
            try {
                currentApi.put(
                    "/api/models/naming",
                    buildJsonObject {
                        put("models", JsonArray(modelKeys.distinct().map(::JsonPrimitive)))
                    }.toString()
                )
                actionMessage = "会话命名候选链已保存"
                open()
            } catch (failure: Exception) {
                error = failure.message ?: "命名候选链保存失败"
            } finally {
                actionBusy = false
            }
        }
    }

    fun loadQuota(providerName: String) {
        val currentApi = apiProvider() ?: return
        scope.launch {
            actionBusy = true
            try {
                quota = currentApi.get("/api/providers/${enc(providerName)}/quota")
            } catch (failure: Exception) {
                error = failure.message ?: "额度读取失败"
            } finally {
                actionBusy = false
            }
        }
    }

    fun startOAuth(providerName: String) {
        val currentApi = apiProvider() ?: return
        scope.launch {
            actionBusy = true
            try {
                oauthFlow = currentApi.post("/api/providers/${enc(providerName)}/oauth/start")
            } catch (failure: Exception) {
                error = failure.message ?: "OAuth 启动失败"
            } finally {
                actionBusy = false
            }
        }
    }

    fun pollOAuth(providerName: String) {
        val currentApi = apiProvider() ?: return
        val flowId = oauthFlow?.objectOrEmpty()?.string("flow_id").orEmpty()
        if (flowId.isBlank()) return
        scope.launch {
            try {
                oauthFlow = currentApi.post(
                    "/api/providers/${enc(providerName)}/oauth/poll",
                    buildJsonObject { put("flow_id", flowId) }.toString()
                )
                open()
            } catch (failure: Exception) {
                error = failure.message ?: "OAuth 状态读取失败"
            }
        }
    }

    fun logoutOAuth(providerName: String) {
        val currentApi = apiProvider() ?: return
        scope.launch {
            try {
                currentApi.delete("/api/providers/${enc(providerName)}/oauth")
                oauthFlow = null
                open()
            } catch (failure: Exception) {
                error = failure.message ?: "OAuth 退出失败"
            }
        }
    }

    private data class Quad(
        val providers: JsonElement,
        val models: JsonElement,
        val presets: JsonElement?,
        val naming: JsonElement?
    )

    private fun enc(value: String): String =
        URLEncoder.encode(value, StandardCharsets.UTF_8)
}
