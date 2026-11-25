package com.spiritscout.desktop.model

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.AccountTree
import androidx.compose.material.icons.outlined.CalendarMonth
import androidx.compose.material.icons.outlined.Dashboard
import androidx.compose.material.icons.outlined.Extension
import androidx.compose.material.icons.outlined.Folder
import androidx.compose.material.icons.outlined.Groups
import androidx.compose.material.icons.outlined.Hub
import androidx.compose.material.icons.outlined.Lan
import androidx.compose.material.icons.outlined.Lightbulb
import androidx.compose.material.icons.outlined.ListAlt
import androidx.compose.material.icons.outlined.ManageAccounts
import androidx.compose.material.icons.outlined.MenuBook
import androidx.compose.material.icons.outlined.Radar
import androidx.compose.material.icons.outlined.Route
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material.icons.outlined.SmartToy
import androidx.compose.material.icons.outlined.Public
import androidx.compose.material.icons.outlined.SwapHoriz
import androidx.compose.material.icons.outlined.Terminal
import androidx.compose.material.icons.outlined.Tune
import androidx.compose.ui.graphics.vector.ImageVector
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.longOrNull
import kotlinx.serialization.json.put
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

enum class NavGroup(val title: String) {
    WORKSPACE("工作空间"),
    CAPABILITY("智能体与能力"),
    CONNECTION("连接与数据"),
    SYSTEM("系统")
}

enum class Section(
    val title: String,
    val subtitle: String,
    val icon: ImageVector,
    val group: NavGroup?,
    val endpoint: String? = null
) {
    TASKS("任务", "创建任务、跟踪执行与继续对话", Icons.Outlined.ListAlt, NavGroup.WORKSPACE, "/api/sessions"),
    PROJECTS("项目", "按项目组织资产、漏洞和会话", Icons.Outlined.Folder, NavGroup.WORKSPACE, "/api/projects"),
    ASSETS("资产收集", "入口、域名、应用与观测范围", Icons.Outlined.Public, NavGroup.WORKSPACE, "/api/assets"),
    DASHBOARD("仪表盘", "执行、费用、缓存和系统态势", Icons.Outlined.Dashboard, NavGroup.WORKSPACE),
    SCHEDULES("自动任务", "定时触发和周期运行", Icons.Outlined.CalendarMonth, NavGroup.WORKSPACE, "/api/schedules"),

    AGENTS("编队", "专项智能体职责、工具与状态", Icons.Outlined.Groups, NavGroup.CAPABILITY, "/api/agents"),
    MODELS("模型", "供应商、模型能力和路由", Icons.Outlined.SmartToy, NavGroup.CAPABILITY, "/api/models"),
    MCP("MCP 管理", "本地与远程工具接入", Icons.Outlined.Hub, NavGroup.CAPABILITY, "/api/resources/mcp"),
    SKILLS("Skill 管理", "知识技能目录和适用条件", Icons.Outlined.MenuBook, NavGroup.CAPABILITY, "/api/resources/skills"),
    LOCAL_TOOLS("本地工具", "暂存、扫描和隔离运行", Icons.Outlined.Terminal, NavGroup.CAPABILITY, "/api/local-tools"),
    EXPERIENCE("经验提炼", "沉淀可复用的测试经验", Icons.Outlined.Lightbulb, NavGroup.CAPABILITY, "/api/experience"),

    INTELLIGENCE("资产情报", "空间测绘与企业归属 Provider", Icons.Outlined.Radar, NavGroup.CONNECTION, "/api/resources/assets/providers"),
    PROXIES("代理池", "节点、线路和出口计划", Icons.Outlined.Route, NavGroup.CONNECTION, "/api/proxies"),
    BROWSER_ACCOUNTS("浏览器账号", "会话隔离与账号绑定", Icons.Outlined.ManageAccounts, NavGroup.CONNECTION, "/api/browser-accounts"),
    TRAFFIC("流量", "HTTP、DNS、TCP 和会话代理记录", Icons.Outlined.SwapHoriz, NavGroup.CONNECTION, "/api/traffic"),

    SETTINGS("设置", "系统资源、后端状态和本地路径", Icons.Outlined.Settings, NavGroup.SYSTEM),

    WORKSPACE("任务工作区", "与灵枢对话并查看执行状态", Icons.Outlined.AccountTree, null);

    val isNavigation: Boolean
        get() = group != null
}

data class MetricItem(
    val label: String,
    val value: String,
    val detail: String,
    val tone: MetricTone = MetricTone.NORMAL
)

enum class MetricTone {
    NORMAL,
    SUCCESS,
    WARNING,
    ERROR
}

data class SessionItem(
    val id: String,
    val title: String,
    val target: String,
    val mode: String,
    val status: String,
    val phase: String,
    val model: String,
    val tokens: Long,
    val cost: Double,
    val rounds: Long,
    val createdAt: String,
    val paused: Boolean,
    val projectId: String = "",
    val sideParentId: String = "",
    val sideAgent: String = "",
    val sideTaskId: String = ""
) {
    val isSideSession: Boolean
        get() = sideParentId.isNotBlank()

    val stateLabel: String
        get() = when {
            paused -> "已暂停"
            status == "running" -> phase.ifBlank { "执行中" }
            status == "completed" -> "已完成"
            status == "failed" -> "失败"
            status == "stopped" -> "已停止"
            else -> status.ifBlank { "等待中" }
        }

    companion object {
        fun fromJson(element: JsonElement): SessionItem {
            val obj = element.objectOrEmpty()
            val side = obj.element("side_session")?.objectOrEmpty()
            return SessionItem(
                id = obj.string("session_id"),
                title = obj.string("title").ifBlank { obj.string("target") }.ifBlank { "未命名任务" },
                target = obj.string("target"),
                mode = obj.string("mode").uppercase(),
                status = obj.string("status"),
                phase = obj.string("phase"),
                model = obj.string("model").ifBlank { "自动" },
                tokens = obj.long("tokens"),
                cost = obj.double("cost_usd"),
                rounds = obj.long("rounds"),
                createdAt = formatTimestamp(obj.double("created_at")),
                paused = obj.boolean("paused"),
                projectId = obj.string("project_id"),
                sideParentId = side?.string("parent_session_id").orEmpty(),
                sideAgent = side?.string("agent").orEmpty(),
                sideTaskId = side?.string("task_id").orEmpty()
            )
        }
    }
}

data class SideAgentOption(
    val actor: String,
    val label: String,
    val status: String = "",
    val modes: Set<String> = emptySet()
)

data class SideMessage(
    val role: String,
    val content: String
)

data class ResourceItem(
    val id: String,
    val title: String,
    val subtitle: String,
    val meta: String,
    val status: String,
    val rawJson: String
)

data class TimelineItem(
    val title: String,
    val body: String,
    val kind: TimelineKind
)

enum class TimelineKind {
    USER,
    MASTER,
    AGENT,
    FINDING,
    SYSTEM
}

enum class WorkspaceTab(val title: String) {
    CHAT("对话"),
    FILES("文件"),
    TOPOLOGY("拓扑"),
    ASSETS("资产"),
    OPPORTUNITIES("机会"),
    CHALLENGES("赛题"),
    VULNERABILITIES("漏洞"),
    FLAGS("Flag"),
    EXPERIENCE("经验"),
    TRAFFIC("流量"),
    BACKGROUND("后台任务"),
    EVENTS("事件"),
    RECORDS("运行记录"),
    DELIVERABLES("交付物"),
    REPORT("报告")
}

data class WorkTask(
    val id: String,
    val title: String,
    val agent: String,
    val status: String,
    val summary: String,
    val routesDone: Int,
    val routesTotal: Int
)

data class WorkspaceSnapshot(
    val session: SessionItem,
    val timeline: List<TimelineItem>,
    val tasks: List<WorkTask>,
    val findings: Int,
    val vulnerabilities: Int,
    val flags: Int,
    val pendingApprovals: List<PendingApprovalItem>,
    val pendingQuestions: List<PendingQuestionItem>,
    val layers: Map<String, Long>,
    val rawJson: String
)

data class PendingApprovalItem(
    val id: String,
    val action: String,
    val purpose: String,
    val detail: String
)

data class PendingQuestionItem(
    val id: String,
    val agent: String,
    val question: String,
    val options: List<String>,
    val multiple: Boolean,
    val secret: Boolean,
    val rawJson: String
)

data class TaskOption(
    val id: String,
    val label: String,
    val detail: String = "",
    val selectedByDefault: Boolean = false
)

data class AssetProviderItem(
    val provider: String,
    val name: String,
    val category: String,
    val enabled: Boolean,
    val keyConfigured: Boolean,
    val keySource: String,
    val storedCredentials: Boolean,
    val version: Long
)

data class SystemResourceSnapshot(
    val cpu: Double,
    val memory: Double,
    val appCpu: Double,
    val appMemoryMb: Double,
    val processCount: Int
)

data class NewTaskRequest(
    val title: String,
    val mode: String,
    val target: String,
    val mission: String,
    val scope: List<String>,
    val model: String,
    val uploadIds: List<String> = emptyList(),
    val generateWriteup: Boolean = false,
    val allowSensitive: Boolean = false,
    val projectId: String = "",
    val proxyPlanId: String = "direct",
    val assetStrategy: String = "edge_first",
    val assetCampaignId: String = "",
    val assetValues: List<String> = emptyList(),
    val excludedAssets: List<String> = emptyList(),
    val platform: String = "",
    val flagFormat: String = "",
    val multipleAnswers: Boolean = false,
    val ctfTypeHints: List<String> = emptyList(),
    val ctfTypeNote: String = "",
    val challengesYaml: String = "",
    val platformYaml: String = "",
    val rulesYaml: String = "",
    val contestType: String = "",
    val budgetTokens: Long? = null,
    val rps: Double = 10.0,
    val noLlm: Boolean = false,
    val acceptRuleConflicts: Boolean = false,
    val browserAccountIds: List<String> = emptyList()
)

fun NewTaskRequest.toPayloadJson(stagedUploadIds: List<String> = emptyList()): JsonObject {
    val selectedAssets = assetValues.map(String::trim).filter(String::isNotBlank).distinct()
    val payloadTarget = selectedAssets.firstOrNull() ?: target.trim()
    val payloadScope = (scope + selectedAssets)
        .map(String::trim)
        .filter(String::isNotBlank)
        .distinct()
    val payloadExcluded = excludedAssets
        .map(String::trim)
        .filter(String::isNotBlank)
        .distinct()
    return buildJsonObject {
        put("title", title.trim())
        put("mode", mode)
        put("target", payloadTarget)
        put("mission", mission.trim())
        put("scope", JsonArray(payloadScope.map(::JsonPrimitive)))
        put("model", model.trim())
        put("generate_wp", generateWriteup)
        put("multiple_answers", multipleAnswers)
        put("allow_sensitive", allowSensitive)
        put("authorized", true)
        put("project_id", projectId.trim())
        put("proxy_plan_id", proxyPlanId.trim().ifBlank { "direct" })
        put("asset_strategy", assetStrategy)
        put("asset_campaign_id", assetCampaignId.trim())
        put("asset_values", JsonArray(selectedAssets.map(::JsonPrimitive)))
        put("excluded_assets", JsonArray(payloadExcluded.map(::JsonPrimitive)))
        put("platform", platform.trim())
        put("flag_format", flagFormat.trim())
        put("ctf_type_hints", JsonArray(ctfTypeHints.map(String::trim).filter(String::isNotBlank).distinct().map(::JsonPrimitive)))
        put("ctf_type_note", ctfTypeNote.trim())
        put("challenges_yaml", challengesYaml.trim().ifBlank { null })
        put("platform_yaml", platformYaml.trim().ifBlank { null })
        put("rules_yaml", rulesYaml.trim().ifBlank { null })
        put("contest_type", contestType.trim())
        put("budget_tokens", budgetTokens)
        put("rps", rps)
        put("no_llm", noLlm)
        put("accept_rule_conflicts", acceptRuleConflicts)
        put(
            "browser_account_ids",
            JsonArray(browserAccountIds.map(String::trim).filter(String::isNotBlank).distinct().map(::JsonPrimitive))
        )
        put(
            "upload_ids",
            JsonArray((uploadIds + stagedUploadIds).map(String::trim).filter(String::isNotBlank).distinct().map(::JsonPrimitive))
        )
    }
}

fun JsonElement.objectOrEmpty(): JsonObject =
    runCatching { jsonObject }.getOrElse { JsonObject(emptyMap()) }

fun JsonElement.element(name: String): JsonElement? =
    (this as? JsonObject)?.get(name)

fun JsonObject.element(name: String): JsonElement? = this[name]

fun JsonElement.string(name: String): String = objectOrEmpty().string(name)

fun JsonElement.long(name: String): Long = objectOrEmpty().long(name)

fun JsonElement.double(name: String): Double = objectOrEmpty().double(name)

fun JsonElement.int(name: String): Int = objectOrEmpty().int(name)

fun JsonElement.boolean(name: String): Boolean = objectOrEmpty().boolean(name)

fun JsonElement.array(name: String): JsonArray = objectOrEmpty().array(name)

fun JsonObject.string(name: String): String =
    element(name)?.let { value ->
        when (value) {
            is JsonPrimitive -> value.contentOrNull.orEmpty()
            else -> value.toString()
        }
    }.orEmpty()

fun JsonObject.long(name: String): Long =
    element(name)?.let { value ->
        (value as? JsonPrimitive)?.longOrNull
            ?: (value as? JsonPrimitive)?.doubleOrNull?.toLong()
    } ?: 0L

fun JsonObject.double(name: String): Double =
    element(name)?.let { value ->
        (value as? JsonPrimitive)?.doubleOrNull
            ?: (value as? JsonPrimitive)?.contentOrNull?.toDoubleOrNull()
    } ?: 0.0

fun JsonObject.int(name: String): Int =
    element(name)?.let { value ->
        (value as? JsonPrimitive)?.intOrNull
            ?: (value as? JsonPrimitive)?.contentOrNull?.toIntOrNull()
    } ?: 0

fun JsonObject.boolean(name: String): Boolean =
    element(name)?.let { value ->
        (value as? JsonPrimitive)?.booleanOrNull
            ?: (value as? JsonPrimitive)?.contentOrNull?.toBooleanStrictOrNull()
    } ?: false

fun JsonObject.array(name: String): JsonArray =
    runCatching { element(name)?.jsonArray }.getOrNull() ?: JsonArray(emptyList())

fun formatTimestamp(value: Double): String {
    if (value <= 0) return "—"
    return runCatching {
        Instant.ofEpochSecond(value.toLong())
            .atZone(ZoneId.systemDefault())
            .format(DateTimeFormatter.ofPattern("MM-dd HH:mm"))
    }.getOrDefault("—")
}
