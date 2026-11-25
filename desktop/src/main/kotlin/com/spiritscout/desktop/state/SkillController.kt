package com.spiritscout.desktop.state

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.spiritscout.desktop.model.array
import com.spiritscout.desktop.model.boolean
import com.spiritscout.desktop.model.double
import com.spiritscout.desktop.model.element
import com.spiritscout.desktop.model.int
import com.spiritscout.desktop.model.long
import com.spiritscout.desktop.model.objectOrEmpty
import com.spiritscout.desktop.model.string
import com.spiritscout.desktop.service.SpiritApi
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.net.URLEncoder
import java.nio.charset.StandardCharsets
import java.nio.file.Path

data class SkillSummaryItem(
    val id: String,
    val description: String,
    val domain: String,
    val tier: String,
    val enabled: Boolean,
    val sourceKind: String,
    val version: Long,
    val updatedAt: Double,
    val tags: List<String>
)

data class SkillDetailState(
    val id: String,
    val version: Long,
    val description: String,
    val domain: String,
    val tier: String,
    val enabled: Boolean,
    val sourceKind: String,
    val tags: List<String>,
    val files: Map<String, String>,
    val rawJson: String
)

class SkillController(
    private val apiProvider: () -> SpiritApi?,
    private val scope: CoroutineScope
) {
    private val prettyJson = Json { prettyPrint = true }
    val items = mutableStateListOf<SkillSummaryItem>()
    var query by mutableStateOf("")
        private set
    var sourceFilter by mutableStateOf("")
        private set
    var tierFilter by mutableStateOf("")
        private set
    var enabledFilter by mutableStateOf<Boolean?>(null)
        private set
    var loading by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set
    var actionMessage by mutableStateOf("")
        private set
    var selectedSkill by mutableStateOf<SkillDetailState?>(null)
        private set
    var detailLoading by mutableStateOf(false)
        private set
    var saving by mutableStateOf(false)
        private set

    fun refresh() {
        val currentApi = apiProvider() ?: return
        scope.launch {
            loading = true
            error = null
            try {
                val collected = mutableListOf<SkillSummaryItem>()
                var offset = 0
                do {
                    val path = buildString {
                        append("/api/resources/skills?limit=100&offset=$offset")
                        if (query.isNotBlank()) append("&q=${enc(query)}")
                        if (sourceFilter.isNotBlank()) append("&source=${enc(sourceFilter)}")
                        if (tierFilter.isNotBlank()) append("&tier=${enc(tierFilter)}")
                        enabledFilter?.let { append("&enabled=$it") }
                    }
                    val root = currentApi.get(path).objectOrEmpty()
                    val page = root.array("items").map(::parseSummary)
                    collected += page
                    val total = root.element("total")?.toString()?.toIntOrNull()
                        ?: root.element("count")?.toString()?.toIntOrNull()
                    offset += page.size
                    if (page.isEmpty() || page.size < 100 || (total != null && offset >= total)) break
                } while (offset < 20_000)
                items.clear()
                items += collected
                if (selectedSkill != null && items.none { it.id == selectedSkill?.id }) {
                    selectedSkill = null
                }
            } catch (failure: Exception) {
                error = failure.message ?: "Skill 列表读取失败"
            } finally {
                loading = false
            }
        }
    }

    fun applyFilters(query: String, source: String, tier: String, enabled: Boolean?) {
        this.query = query.trim()
        sourceFilter = source
        tierFilter = tier
        enabledFilter = enabled
        refresh()
    }

    fun selectSkill(skillId: String) {
        val currentApi = apiProvider() ?: return
        scope.launch {
            detailLoading = true
            error = null
            try {
                selectedSkill = parseDetail(
                    currentApi.get("/api/resources/skills/${enc(skillId)}")
                )
            } catch (failure: Exception) {
                error = failure.message ?: "Skill 详情读取失败"
                selectedSkill = null
            } finally {
                detailLoading = false
            }
        }
    }

    fun saveFile(path: String, content: String) {
        val currentApi = apiProvider() ?: return
        val detail = selectedSkill ?: return
        if (path.isBlank()) return
        scope.launch {
            saving = true
            error = null
            try {
                val result = currentApi.put(
                    "/api/resources/skills/${enc(detail.id)}/file",
                    buildJsonObject {
                        put("path", path)
                        put("content", content)
                        put("expected_version", detail.version)
                    }.toString()
                ).objectOrEmpty()
                val version = result.element("version")?.toString()?.toLongOrNull() ?: detail.version
                selectedSkill = detail.copy(
                    version = version,
                    files = detail.files + (path to content)
                )
                actionMessage = "已保存 $path"
                refresh()
            } catch (failure: Exception) {
                error = failure.message ?: "Skill 文件保存失败"
            } finally {
                saving = false
            }
        }
    }

    fun saveSkill(
        originalId: String?,
        skillId: String,
        description: String,
        domain: String,
        tier: String,
        enabled: Boolean,
        body: String = ""
    ) {
        val currentApi = apiProvider() ?: return
        if (skillId.isBlank()) {
            error = "Skill ID 不能为空。"
            return
        }
        val detail = selectedSkill
        scope.launch {
            saving = true
            error = null
            try {
                val data = buildJsonObject {
                    put("skill_id", skillId.trim())
                    put("description", description.trim())
                    put("domain", domain.trim().ifBlank { "custom" })
                    put("tier", tier)
                    put("enabled", enabled)
                    put("aliases", JsonArray(emptyList()))
                    put("tags", JsonArray(emptyList()))
                    if (originalId == null) {
                        put("body", body)
                        put("files", buildJsonObject { put("SKILL.md", body) })
                    }
                }
                val payload = buildJsonObject {
                    put("data", data)
                    put("expected_version", if (originalId == null) 0 else detail?.version ?: 0)
                }
                currentApi.put(
                    "/api/resources/skills/${enc(originalId ?: skillId.trim())}",
                    payload.toString()
                )
                actionMessage = "Skill 配置已保存"
                refresh()
                selectSkill(skillId.trim())
            } catch (failure: Exception) {
                error = failure.message ?: "Skill 配置保存失败"
            } finally {
                saving = false
            }
        }
    }

    fun deleteSkill(skillId: String) {
        val currentApi = apiProvider() ?: return
        val version = items.firstOrNull { it.id == skillId }?.version
            ?: selectedSkill?.version
            ?: return
        scope.launch {
            saving = true
            error = null
            try {
                currentApi.delete(
                    "/api/resources/skills/${enc(skillId)}?expected_version=$version"
                )
                if (selectedSkill?.id == skillId) selectedSkill = null
                refresh()
            } catch (failure: Exception) {
                error = failure.message ?: "Skill 删除失败"
            } finally {
                saving = false
            }
        }
    }

    fun importArchive(path: Path) {
        val currentApi = apiProvider() ?: return
        scope.launch {
            saving = true
            error = null
            try {
                val result = currentApi.importSkillArchive(path).objectOrEmpty()
                val warnings = result.array("warnings").map { it.toString().trim('"') }
                actionMessage = "Skill 导入完成" +
                    warnings.takeIf { it.isNotEmpty() }?.let { " · ${it.joinToString("；")}" }.orEmpty()
                refresh()
            } catch (failure: Exception) {
                error = failure.message ?: "Skill 导入失败"
            } finally {
                saving = false
            }
        }
    }

    private fun parseSummary(raw: JsonElement): SkillSummaryItem {
        val item = raw.objectOrEmpty()
        return SkillSummaryItem(
            id = item.string("skill_id"),
            description = item.string("description"),
            domain = item.string("domain"),
            tier = item.string("tier"),
            enabled = item.boolean("enabled"),
            sourceKind = item.string("source_kind"),
            version = item.long("version"),
            updatedAt = item.double("updated_at"),
            tags = item.array("tags").map { it.toString().trim('"') }
        )
    }

    private fun parseDetail(raw: JsonElement): SkillDetailState {
        val item = raw.objectOrEmpty()
        val fileObject = item.element("files")?.objectOrEmpty()
        val files = if (fileObject != null && fileObject.isNotEmpty()) {
            fileObject.mapValues { (_, value) ->
                when (value) {
                    is JsonPrimitive -> value.content
                    else -> value.toString()
                }
            }
        } else {
            mapOf("SKILL.md" to item.string("body"))
        }
        return SkillDetailState(
            id = item.string("skill_id"),
            version = item.long("version"),
            description = item.string("description"),
            domain = item.string("domain"),
            tier = item.string("tier"),
            enabled = item.boolean("enabled"),
            sourceKind = item.string("source_kind"),
            tags = item.array("tags").map { it.toString().trim('"') },
            files = files,
            rawJson = prettyJson.encodeToString(JsonElement.serializer(), raw)
        )
    }

    private fun enc(value: String): String =
        URLEncoder.encode(value, StandardCharsets.UTF_8)
}
