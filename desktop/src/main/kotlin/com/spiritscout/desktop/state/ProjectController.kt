package com.spiritscout.desktop.state

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.spiritscout.desktop.model.array
import com.spiritscout.desktop.model.double
import com.spiritscout.desktop.model.int
import com.spiritscout.desktop.model.objectOrEmpty
import com.spiritscout.desktop.model.string
import com.spiritscout.desktop.service.SpiritApi
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.net.URLEncoder
import java.nio.charset.StandardCharsets

data class ProjectRow(
    val id: String,
    val name: String,
    val description: String,
    val assetCount: Int,
    val findingCount: Int,
    val sessionCount: Int,
    val lastSeen: Double
)

class ProjectController(
    private val apiProvider: () -> SpiritApi?,
    private val scope: CoroutineScope
) {
    val projects = mutableStateListOf<ProjectRow>()
    var loading by mutableStateOf(false)
        private set
    var saving by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set
    var message by mutableStateOf("")
        private set
    var projectTargets by mutableStateOf<JsonElement?>(null)
        private set
    var detailLoading by mutableStateOf(false)
        private set

    fun refresh() {
        val currentApi = apiProvider() ?: return
        scope.launch {
            loading = true
            error = null
            try {
                projects.clear()
                projects += currentApi.get("/api/projects").array("projects").map { raw ->
                    val item = raw.objectOrEmpty()
                    ProjectRow(
                        id = item.string("project_id"),
                        name = item.string("name"),
                        description = item.string("description"),
                        assetCount = item.int("asset_count"),
                        findingCount = item.int("finding_count"),
                        sessionCount = item.int("session_count"),
                        lastSeen = item.double("last_seen")
                    )
                }
            } catch (failure: Exception) {
                error = failure.message ?: "项目读取失败"
            } finally {
                loading = false
            }
        }
    }

    fun save(
        originalId: String?,
        name: String,
        description: String
    ) {
        val currentApi = apiProvider() ?: return
        if (name.isBlank()) {
            error = "项目名称不能为空。"
            return
        }
        scope.launch {
            saving = true
            error = null
            try {
                val payload = buildJsonObject {
                    put("name", name.trim())
                    put("description", description.trim())
                }
                if (originalId == null) {
                    currentApi.post("/api/projects", payload.toString())
                } else {
                    currentApi.patch("/api/projects/${enc(originalId)}", payload.toString())
                }
                message = "项目已保存"
                refresh()
            } catch (failure: Exception) {
                error = failure.message ?: "项目保存失败"
            } finally {
                saving = false
            }
        }
    }

    fun delete(projectId: String) {
        val currentApi = apiProvider() ?: return
        scope.launch {
            saving = true
            error = null
            try {
                currentApi.delete("/api/projects/${enc(projectId)}?confirm=true")
                message = "项目已删除；资产和历史记录已转为未分类"
                refresh()
            } catch (failure: Exception) {
                error = failure.message ?: "项目删除失败"
            } finally {
                saving = false
            }
        }
    }

    fun loadDetails(projectId: String) {
        val currentApi = apiProvider() ?: return
        if (projectId.isBlank()) {
            projectTargets = null
            return
        }
        scope.launch {
            detailLoading = true
            error = null
            try {
                projectTargets = currentApi.get("/api/projects/${enc(projectId)}/asset-targets")
            } catch (failure: Exception) {
                error = failure.message ?: "项目关联详情读取失败"
                projectTargets = null
            } finally {
                detailLoading = false
            }
        }
    }

    private fun enc(value: String): String =
        URLEncoder.encode(value, StandardCharsets.UTF_8)
}
