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

data class LocalToolItem(
    val name: String,
    val file: String,
    val path: String,
    val dir: String,
    val ext: String,
    val size: Long
)

data class LocalToolsConfig(
    val enabled: Boolean,
    val dirs: List<String>,
    val timeoutSeconds: Int,
    val maxDepth: Int,
    val maxFiles: Int,
    val maxStageMb: Int
)

class LocalToolsController(
    private val apiProvider: () -> SpiritApi?,
    private val scope: CoroutineScope
) {
    val tools = mutableStateListOf<LocalToolItem>()
    var config by mutableStateOf(LocalToolsConfig(false, emptyList(), 30, 4, 5000, 256))
        private set
    var indexed by mutableStateOf(0)
        private set
    var scannedAt by mutableStateOf(0.0)
        private set
    var notice by mutableStateOf("")
        private set
    var runsDir by mutableStateOf("")
        private set
    var loading by mutableStateOf(false)
        private set
    var saving by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set
    var message by mutableStateOf("")
        private set

    fun refresh(query: String = "") {
        val currentApi = apiProvider() ?: return
        scope.launch {
            loading = true
            error = null
            try {
                parse(
                    currentApi.get(
                        "/api/local-tools?limit=500" + if (query.isBlank()) "" else "&q=${enc(query)}"
                    )
                )
            } catch (failure: Exception) {
                error = failure.message ?: "本地工具读取失败"
            } finally {
                loading = false
            }
        }
    }

    fun save(
        enabled: Boolean,
        dirs: List<String>,
        timeoutSeconds: String,
        maxDepth: String,
        maxFiles: String,
        maxStageMb: String
    ) {
        val currentApi = apiProvider() ?: return
        scope.launch {
            saving = true
            error = null
            try {
                val payload = buildJsonObject {
                    put("enabled", enabled)
                    put("dirs", JsonArray(dirs.distinct().map(::JsonPrimitive)))
                    timeoutSeconds.toIntOrNull()?.let { put("timeout_seconds", it) }
                    maxDepth.toIntOrNull()?.let { put("max_depth", it) }
                    maxFiles.toIntOrNull()?.let { put("max_files", it) }
                    maxStageMb.toIntOrNull()?.let { put("max_stage_mb", it) }
                }
                parse(currentApi.put("/api/local-tools", payload.toString()))
                message = "本地工具配置已保存并重新扫描"
            } catch (failure: Exception) {
                error = failure.message ?: "本地工具配置保存失败"
            } finally {
                saving = false
            }
        }
    }

    fun rescan() = action("/api/local-tools/refresh", "索引已刷新")

    fun cleanup() = action("/api/local-tools/cleanup", "暂存目录已清理", thenReload = true)

    private fun action(path: String, success: String, thenReload: Boolean = false) {
        val currentApi = apiProvider() ?: return
        scope.launch {
            saving = true
            error = null
            try {
                val result = currentApi.post(path)
                message = success
                if (thenReload) refresh() else if (result.objectOrEmpty().element("config") != null) parse(result)
            } catch (failure: Exception) {
                error = failure.message ?: "本地工具操作失败"
            } finally {
                saving = false
            }
        }
    }

    private fun parse(root: JsonElement) {
        val obj = root.objectOrEmpty()
        val cfg = obj.element("config")?.objectOrEmpty()
        config = LocalToolsConfig(
            enabled = cfg?.boolean("enabled") ?: false,
            dirs = cfg?.array("dirs").orEmpty().map { it.toString().trim('"') },
            timeoutSeconds = cfg?.int("timeout_seconds") ?: 30,
            maxDepth = cfg?.int("max_depth") ?: 4,
            maxFiles = cfg?.int("max_files") ?: 5000,
            maxStageMb = cfg?.int("max_stage_mb") ?: 256
        )
        indexed = obj.int("indexed")
        val summary = obj.element("summary")?.objectOrEmpty()
        scannedAt = summary?.double("scanned_at") ?: 0.0
        notice = obj.string("notice")
        runsDir = obj.string("runs_dir")
        tools.clear()
        tools += obj.array("tools").map { raw ->
            val item = raw.objectOrEmpty()
            LocalToolItem(
                name = item.string("name"),
                file = item.string("file"),
                path = item.string("path"),
                dir = item.string("dir"),
                ext = item.string("ext"),
                size = item.element("size")?.toString()?.toLongOrNull() ?: 0
            )
        }
    }

    private fun enc(value: String): String =
        java.net.URLEncoder.encode(value, java.nio.charset.StandardCharsets.UTF_8)
}
