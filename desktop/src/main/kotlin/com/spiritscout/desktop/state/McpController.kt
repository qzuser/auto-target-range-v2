package com.spiritscout.desktop.state

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.spiritscout.desktop.model.array
import com.spiritscout.desktop.model.boolean
import com.spiritscout.desktop.model.double
import com.spiritscout.desktop.model.element
import com.spiritscout.desktop.model.long
import com.spiritscout.desktop.model.objectOrEmpty
import com.spiritscout.desktop.model.string
import com.spiritscout.desktop.service.SpiritApi
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.net.URLEncoder
import java.nio.charset.StandardCharsets

data class McpItem(
    val id: String,
    val version: Long,
    val origin: String,
    val transport: String,
    val command: String,
    val args: List<String>,
    val url: String,
    val timeout: Double,
    val defaultRisk: String,
    val riskByAction: Boolean,
    val internetSearch: Boolean,
    val scopeEnforcement: String,
    val targetParams: List<String>,
    val allowedAgents: List<String>,
    val enabled: Boolean,
    val headerKeys: List<String>,
    val envKeys: List<String>,
    val data: JsonObject,
    val rawJson: String
)

class McpController(
    private val apiProvider: () -> SpiritApi?,
    private val scope: CoroutineScope
) {
    private val prettyJson = Json { prettyPrint = true }
    val items = mutableStateListOf<McpItem>()
    var query by mutableStateOf("")
        private set
    var transportFilter by mutableStateOf("")
        private set
    var riskFilter by mutableStateOf("")
        private set
    var enabledFilter by mutableStateOf<Boolean?>(null)
        private set
    var loading by mutableStateOf(false)
        private set
    var saving by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set
    var message by mutableStateOf("")
        private set

    fun refresh() {
        val currentApi = apiProvider() ?: return
        scope.launch {
            loading = true
            error = null
            try {
                val collected = mutableListOf<McpItem>()
                var offset = 0
                do {
                    val path = buildString {
                        append("/api/resources/mcp?limit=100&offset=$offset")
                        if (query.isNotBlank()) append("&q=${enc(query)}")
                        if (transportFilter.isNotBlank()) append("&transport=${enc(transportFilter)}")
                        if (riskFilter.isNotBlank()) append("&risk=${enc(riskFilter)}")
                        enabledFilter?.let { append("&enabled=$it") }
                    }
                    val root = currentApi.get(path).objectOrEmpty()
                    val page = root.array("items").map(::parseItem)
                    collected += page
                    val total = root.element("total")?.toString()?.toIntOrNull()
                        ?: root.element("count")?.toString()?.toIntOrNull()
                    offset += page.size
                    if (page.isEmpty() || page.size < 100 || (total != null && offset >= total)) break
                } while (offset < 20_000)
                items.clear()
                items += collected
            } catch (failure: Exception) {
                error = failure.message ?: "MCP 列表读取失败"
            } finally {
                loading = false
            }
        }
    }

    fun applyFilters(query: String, transport: String, risk: String, enabled: Boolean?) {
        this.query = query.trim()
        transportFilter = transport
        riskFilter = risk
        enabledFilter = enabled
        refresh()
    }

    fun save(
        original: McpItem?,
        name: String,
        transport: String,
        command: String,
        argsText: String,
        url: String,
        envText: String,
        headersText: String,
        timeoutText: String,
        defaultRisk: String,
        riskByAction: Boolean,
        internetSearch: Boolean,
        scopeEnforcement: String,
        targetParamsText: String,
        allowedAgents: List<String>,
        riskOverrideText: String = "",
        enabled: Boolean
    ) {
        val currentApi = apiProvider() ?: return
        if (name.isBlank()) {
            error = "MCP 名称不能为空。"
            return
        }
        scope.launch {
            saving = true
            error = null
            try {
                val data = (original?.data ?: JsonObject(emptyMap())).toMutableMap().apply {
                    put("name", JsonPrimitive(name.trim()))
                    put("transport", JsonPrimitive(transport))
                    put("command", JsonPrimitive(command.trim()))
                    put("args", JsonArray(splitValues(argsText).map(::JsonPrimitive)))
                    put("url", JsonPrimitive(url.trim()))
                    put(
                        "env",
                        if (envText.isBlank()) original?.data?.get("env") ?: JsonObject(emptyMap())
                        else keyValueObject(envText)
                    )
                    put(
                        "headers",
                        if (headersText.isBlank()) original?.data?.get("headers") ?: JsonObject(emptyMap())
                        else keyValueObject(headersText)
                    )
                    put("timeout", JsonPrimitive(timeoutText.toDoubleOrNull() ?: 180.0))
                    put("default_risk", JsonPrimitive(defaultRisk))
                    put("risk_by_action", JsonPrimitive(riskByAction))
                    put("internet_search", JsonPrimitive(internetSearch))
                    put("scope_enforcement", JsonPrimitive(scopeEnforcement))
                    put(
                        "target_params",
                        if (targetParamsText.isBlank()) original?.data?.get("target_params")
                            ?: JsonArray(emptyList())
                        else JsonArray(splitValues(targetParamsText).map(::JsonPrimitive))
                    )
                    put(
                        "allowed_agents",
                        if (allowedAgents.isEmpty() && original != null) {
                            original.data["allowed_agents"] ?: JsonArray(emptyList())
                        } else {
                            JsonArray(allowedAgents.map(::JsonPrimitive))
                        }
                    )
                    put(
                        "tool_risk_overrides",
                        if (riskOverrideText.isBlank()) {
                            original?.data?.get("tool_risk_overrides") ?: JsonObject(emptyMap())
                        } else {
                            keyValueObject(riskOverrideText)
                        }
                    )
                    put("enabled", JsonPrimitive(enabled))
                }
                val payload = buildJsonObject {
                    put("data", JsonObject(data))
                    put("expected_version", original?.version ?: 0)
                }
                currentApi.put(
                    "/api/resources/mcp/${enc(name.trim())}",
                    payload.toString()
                )
                message = "MCP 配置已保存"
                refresh()
            } catch (failure: Exception) {
                error = failure.message ?: "MCP 保存失败"
            } finally {
                saving = false
            }
        }
    }

    fun delete(item: McpItem) {
        val currentApi = apiProvider() ?: return
        scope.launch {
            saving = true
            error = null
            try {
                currentApi.delete(
                    "/api/resources/mcp/${enc(item.id)}?expected_version=${item.version}"
                )
                refresh()
            } catch (failure: Exception) {
                error = failure.message ?: "MCP 删除失败"
            } finally {
                saving = false
            }
        }
    }

    private fun parseItem(raw: JsonElement): McpItem {
        val item = raw.objectOrEmpty()
        val data = item.element("data")?.objectOrEmpty() ?: JsonObject(emptyMap())
        return McpItem(
            id = item.string("id"),
            version = item.long("version"),
            origin = item.string("origin"),
            transport = data.string("transport"),
            command = data.string("command"),
            args = data.array("args").map { it.toString().trim('"') },
            url = data.string("url"),
            timeout = data.double("timeout"),
            defaultRisk = data.string("default_risk"),
            riskByAction = data.boolean("risk_by_action"),
            internetSearch = data.boolean("internet_search"),
            scopeEnforcement = data.string("scope_enforcement"),
            targetParams = data.array("target_params").map { it.toString().trim('"') },
            allowedAgents = data.array("allowed_agents").map { it.toString().trim('"') },
            enabled = data.boolean("enabled"),
            headerKeys = data.array("headers_keys").map { it.toString().trim('"') },
            envKeys = data.array("env_keys").map { it.toString().trim('"') },
            data = data,
            rawJson = prettyJson.encodeToString(JsonElement.serializer(), raw)
        )
    }

    private fun keyValueObject(text: String): JsonObject = JsonObject(
        buildMap {
            text.lines().forEach { line ->
                val index = line.indexOf('=')
                if (index > 0) {
                    val key = line.substring(0, index).trim()
                    val value = line.substring(index + 1).trim()
                    if (key.isNotBlank()) put(key, JsonPrimitive(value))
                }
            }
        }
    )

    private fun splitValues(text: String): List<String> =
        text.split('\n', ',', '，')
            .map(String::trim)
            .filter(String::isNotBlank)
            .distinct()

    private fun enc(value: String): String =
        URLEncoder.encode(value, StandardCharsets.UTF_8)
}
