package com.spiritscout.desktop.state

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.spiritscout.desktop.model.array
import com.spiritscout.desktop.model.element
import com.spiritscout.desktop.model.objectOrEmpty
import com.spiritscout.desktop.model.string
import com.spiritscout.desktop.service.SpiritApi
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.net.URLEncoder
import java.nio.charset.StandardCharsets

data class AgentRow(
    val key: String,
    val name: String,
    val duty: String,
    val modes: List<String>,
    val status: String,
    val assignedModel: String
)

class AgentController(
    private val apiProvider: () -> SpiritApi?,
    private val scope: CoroutineScope
) {
    val agents = mutableStateListOf<AgentRow>()
    val models = mutableStateListOf<String>()
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
                val root = currentApi.get("/api/agents").objectOrEmpty()
                val assignmentObject = root.element("assignments")?.objectOrEmpty()
                models.clear()
                models += root.array("models").mapNotNull { raw ->
                    raw.objectOrEmpty().string("key")
                        .ifBlank { raw.objectOrEmpty().string("model") }
                        .takeIf(String::isNotBlank)
                }
                agents.clear()
                agents += root.array("roster").map { raw ->
                    val item = raw.objectOrEmpty()
                    val key = item.string("key")
                    AgentRow(
                        key = key,
                        name = item.string("name").ifBlank { key },
                        duty = item.string("duty"),
                        modes = item.array("modes").map { it.toString().trim('"') },
                        status = item.string("status"),
                        assignedModel = assignmentObject?.string(key).orEmpty()
                    )
                }
            } catch (failure: Exception) {
                error = failure.message ?: "编队读取失败"
            } finally {
                loading = false
            }
        }
    }

    fun bind(agentKey: String, model: String) {
        val currentApi = apiProvider() ?: return
        scope.launch {
            saving = true
            error = null
            try {
                currentApi.put(
                    "/api/agents/${enc(agentKey)}",
                    buildJsonObject { put("model", model) }.toString()
                )
                message = if (model.isBlank()) "已恢复档位路由" else "模型绑定已保存"
                refresh()
            } catch (failure: Exception) {
                error = failure.message ?: "模型绑定失败"
            } finally {
                saving = false
            }
        }
    }

    fun bindAll(model: String) {
        if (model.isBlank()) return
        saving = true
        error = null
        val keys = agents.filter { it.status == "available" }.map { it.key }
        scope.launch {
            try {
                keys.forEach { key ->
                    apiProvider()?.put(
                        "/api/agents/${enc(key)}",
                        buildJsonObject { put("model", model) }.toString()
                    )
                }
                message = "已将 $model 应用到 ${keys.size} 个可用角色"
                refresh()
            } catch (failure: Exception) {
                error = failure.message ?: "批量模型绑定失败"
            } finally {
                saving = false
            }
        }
    }

    private fun enc(value: String): String =
        URLEncoder.encode(value, StandardCharsets.UTF_8)
}
