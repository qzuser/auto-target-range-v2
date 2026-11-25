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
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

data class ProxyNodeRow(
    val id: String,
    val name: String,
    val type: String,
    val server: String,
    val port: Int,
    val kind: String,
    val selectable: Boolean,
    val sourceId: String,
    val tlsVerification: String,
    val benchmark: JsonElement?
)

data class ProxyPlanRow(
    val id: String,
    val name: String,
    val nodes: List<String>
)

data class ProxySubscriptionRow(
    val id: String,
    val name: String,
    val nodeCount: Int,
    val noticeCount: Int,
    val diagnostic: String,
    val updatedAt: Double
)

class ProxyController(
    private val apiProvider: () -> SpiritApi?,
    private val scope: CoroutineScope
) {
    val nodes = mutableStateListOf<ProxyNodeRow>()
    val plans = mutableStateListOf<ProxyPlanRow>()
    val subscriptions = mutableStateListOf<ProxySubscriptionRow>()
    var version by mutableStateOf(0L)
        private set
    var mihomoAvailable by mutableStateOf(false)
        private set
    var loading by mutableStateOf(false)
        private set
    var actionBusy by mutableStateOf(false)
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
                parse(currentApi.get("/api/proxies"))
            } catch (failure: Exception) {
                error = failure.message ?: "代理池读取失败"
            } finally {
                loading = false
            }
        }
    }

    fun importNodes(content: String) {
        if (content.isBlank()) {
            error = "请粘贴 Clash/Mihomo 节点配置。"
            return
        }
        mutate("import") {
            buildJsonObject {
                put("content", content)
                put("version", version)
            }
        }
    }

    fun subscribe(name: String, url: String) {
        if (name.isBlank() || url.isBlank()) {
            error = "订阅名称和地址不能为空。"
            return
        }
        mutate("subscribe") {
            buildJsonObject {
                put("name", name.trim())
                put("url", url.trim())
                put("version", version)
            }
        }
    }

    fun refreshSubscription(subscriptionId: String) {
        mutate("refresh", refreshAfter = true) {
            buildJsonObject {
                put("id", subscriptionId)
                put("version", version)
            }
        }
    }

    fun createPlan(name: String, nodeIds: List<String>) {
        if (name.isBlank() || nodeIds.isEmpty()) {
            error = "请填写方案名称并选择至少一个节点。"
            return
        }
        mutate("plan") {
            buildJsonObject {
                put("name", name.trim())
                put("nodes", JsonArray(nodeIds.map(::JsonPrimitive)))
                put("version", version)
            }
        }
    }

    fun benchmark(nodeIds: List<String>, mode: String = "latency") {
        if (nodeIds.isEmpty()) {
            error = "请选择要测速的节点。"
            return
        }
        mutate("benchmark") {
            buildJsonObject {
                put("nodes", JsonArray(nodeIds.map(::JsonPrimitive)))
                put("mode", mode)
                put("version", version)
            }
        }
    }

    fun delete(kind: String, id: String) {
        mutate("delete") {
            buildJsonObject {
                put("kind", kind)
                put("id", id)
                put("version", version)
            }
        }
    }

    private fun mutate(
        operation: String,
        refreshAfter: Boolean = false,
        payload: () -> kotlinx.serialization.json.JsonObject
    ) {
        val currentApi = apiProvider() ?: return
        scope.launch {
            actionBusy = true
            error = null
            try {
                val result = currentApi.post("/api/proxies/$operation", payload().toString())
                parse(result)
                message = if (refreshAfter) "订阅已刷新" else "代理池已更新"
            } catch (failure: Exception) {
                error = failure.message ?: "代理池操作失败"
            } finally {
                actionBusy = false
            }
        }
    }

    private fun parse(root: JsonElement) {
        val obj = root.objectOrEmpty()
        version = obj.element("version")?.toString()?.toLongOrNull() ?: 0
        mihomoAvailable = obj.boolean("mihomo_available")
        nodes.clear()
        nodes += obj.array("nodes").map { raw ->
            val item = raw.objectOrEmpty()
            ProxyNodeRow(
                id = item.string("id"),
                name = item.string("name"),
                type = item.string("type"),
                server = item.string("server"),
                port = item.int("port"),
                kind = item.string("kind"),
                selectable = item.boolean("selectable"),
                sourceId = item.string("source_id"),
                tlsVerification = item.string("tls_verification"),
                benchmark = item.element("benchmark")
            )
        }
        plans.clear()
        plans += obj.array("plans").map { raw ->
            val item = raw.objectOrEmpty()
            ProxyPlanRow(
                id = item.string("id"),
                name = item.string("name"),
                nodes = item.array("nodes").map { it.toString().trim('"') }
            )
        }
        subscriptions.clear()
        subscriptions += obj.array("subscriptions").map { raw ->
            val item = raw.objectOrEmpty()
            ProxySubscriptionRow(
                id = item.string("id"),
                name = item.string("name"),
                nodeCount = item.int("node_count"),
                noticeCount = item.int("notice_count"),
                diagnostic = item.string("diagnostic"),
                updatedAt = item.double("updated_at")
            )
        }
    }
}
