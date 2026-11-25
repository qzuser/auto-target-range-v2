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
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.net.URLEncoder
import java.nio.charset.StandardCharsets

data class ScheduleRow(
    val id: String,
    val name: String,
    val message: String,
    val nextRun: Double,
    val intervalSeconds: Int?,
    val enabled: Boolean,
    val state: String,
    val error: String,
    val lastRun: Double,
    val retryAt: Double,
    val sessionTitle: String,
    val kind: String,
    val mode: String,
    val model: String,
    val projectId: String,
    val target: String,
    val scope: List<String>
)

data class ScheduleRunRow(
    val id: String,
    val due: Double,
    val createdAt: Double,
    val state: String,
    val status: String,
    val error: String,
    val sessionId: String
)

class ScheduleController(
    private val apiProvider: () -> SpiritApi?,
    private val scope: CoroutineScope
) {
    val items = mutableStateListOf<ScheduleRow>()
    val runs = mutableStateListOf<ScheduleRunRow>()
    var loading by mutableStateOf(false)
        private set
    var saving by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set
    var message by mutableStateOf("")
        private set
    var selectedId by mutableStateOf("")
        private set

    fun refresh() {
        val currentApi = apiProvider() ?: return
        scope.launch {
            loading = true
            error = null
            try {
                items.clear()
                items += currentApi.get("/api/schedules").array("items").map { raw ->
                    val item = raw.objectOrEmpty()
                    val task = item.element("task")?.objectOrEmpty()
                    ScheduleRow(
                        id = item.string("id"),
                        name = item.string("name"),
                        message = item.string("message"),
                        nextRun = item.double("next_run"),
                        intervalSeconds = item.element("interval_seconds")?.toString()?.toIntOrNull(),
                        enabled = item.boolean("enabled"),
                        state = item.string("state"),
                        error = item.string("error"),
                        lastRun = item.double("last_run"),
                        retryAt = item.double("retry_at"),
                        sessionTitle = item.string("session_title"),
                        kind = item.string("kind"),
                        mode = task?.string("mode").orEmpty().ifBlank { "src" },
                        model = task?.string("model").orEmpty(),
                        projectId = task?.string("project_id").orEmpty(),
                        target = task?.string("target").orEmpty(),
                        scope = task?.array("scope").orEmpty().map { it.toString().trim('"') }
                    )
                }
                if (items.none { it.id == selectedId }) {
                    selectedId = items.firstOrNull()?.id.orEmpty()
                    runs.clear()
                }
            } catch (failure: Exception) {
                error = failure.message ?: "自动任务读取失败"
            } finally {
                loading = false
            }
        }
    }

    fun select(id: String) {
        selectedId = id
        loadRuns(id)
    }

    fun loadRuns(id: String) {
        val currentApi = apiProvider() ?: return
        if (id.isBlank()) return
        scope.launch {
            try {
                runs.clear()
                runs += currentApi.get("/api/schedules/${enc(id)}/runs").array("items").map { raw ->
                    val item = raw.objectOrEmpty()
                    ScheduleRunRow(
                        id = item.string("run_id"),
                        due = item.double("due"),
                        createdAt = item.double("created_at"),
                        state = item.string("state"),
                        status = item.string("status"),
                        error = item.string("error"),
                        sessionId = item.string("session_id")
                    )
                }
            } catch (failure: Exception) {
                error = failure.message ?: "运行历史读取失败"
            }
        }
    }

    fun create(
        name: String,
        message: String,
        runAt: String,
        intervalText: String,
        mode: String,
        model: String,
        projectId: String,
        target: String,
        scopeText: String
    ) {
        val currentApi = apiProvider() ?: return
        if (name.isBlank() || message.isBlank() || runAt.isBlank()) {
            error = "名称、任务消息和下次执行时间不能为空。"
            return
        }
        scope.launch {
            saving = true
            error = null
            try {
                val payload = buildJsonObject {
                    put("session_id", "")
                    put("name", name.trim())
                    put("message", message.trim())
                    put("run_at", runAt.trim())
                    intervalText.trim().toIntOrNull()?.let { put("interval_seconds", it) }
                    put("mode", mode)
                    put("model", model.trim())
                    put("project_id", projectId.trim())
                    put("target", target.trim())
                    put("scope", JsonArray(scopeText.lines().map(String::trim).filter(String::isNotBlank).map(::JsonPrimitive)))
                }
                val created = currentApi.post("/api/schedules", payload.toString()).objectOrEmpty()
                this@ScheduleController.message = "自动任务已创建"
                refresh()
                created.string("id").takeIf(String::isNotBlank)?.let(::select)
            } catch (failure: Exception) {
                error = failure.message ?: "自动任务创建失败"
            } finally {
                saving = false
            }
        }
    }

    fun toggle(item: ScheduleRow) {
        val currentApi = apiProvider() ?: return
        scope.launch {
            saving = true
            error = null
            try {
                currentApi.patch(
                    "/api/schedules/${enc(item.id)}",
                    buildJsonObject { put("enabled", !item.enabled) }.toString()
                )
                message = if (item.enabled) "自动任务已停用" else "自动任务已启用"
                refresh()
            } catch (failure: Exception) {
                error = failure.message ?: "自动任务状态更新失败"
            } finally {
                saving = false
            }
        }
    }

    fun delete(item: ScheduleRow) {
        val currentApi = apiProvider() ?: return
        scope.launch {
            saving = true
            error = null
            try {
                currentApi.delete("/api/schedules/${enc(item.id)}")
                message = "自动任务已删除"
                refresh()
            } catch (failure: Exception) {
                error = failure.message ?: "自动任务删除失败"
            } finally {
                saving = false
            }
        }
    }

    private fun enc(value: String): String =
        URLEncoder.encode(value, StandardCharsets.UTF_8)
}
