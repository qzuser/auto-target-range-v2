package com.spiritscout.desktop

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.spiritscout.desktop.model.MetricItem
import com.spiritscout.desktop.model.MetricTone
import com.spiritscout.desktop.model.AssetProviderItem
import com.spiritscout.desktop.model.NewTaskRequest
import com.spiritscout.desktop.model.PendingApprovalItem
import com.spiritscout.desktop.model.PendingQuestionItem
import com.spiritscout.desktop.model.JsonActionState
import com.spiritscout.desktop.model.ResourceItem
import com.spiritscout.desktop.model.ResourcePaging
import com.spiritscout.desktop.model.Section
import com.spiritscout.desktop.model.SessionItem
import com.spiritscout.desktop.model.SideAgentOption
import com.spiritscout.desktop.model.SideMessage
import com.spiritscout.desktop.model.SystemResourceSnapshot
import com.spiritscout.desktop.model.TaskOption
import com.spiritscout.desktop.model.TimelineItem
import com.spiritscout.desktop.model.TimelineKind
import com.spiritscout.desktop.model.WorkTask
import com.spiritscout.desktop.model.WorkspaceSnapshot
import com.spiritscout.desktop.model.WorkspaceTab
import com.spiritscout.desktop.model.array
import com.spiritscout.desktop.model.boolean
import com.spiritscout.desktop.model.double
import com.spiritscout.desktop.model.element
import com.spiritscout.desktop.model.int
import com.spiritscout.desktop.model.long
import com.spiritscout.desktop.model.objectOrEmpty
import com.spiritscout.desktop.model.string
import com.spiritscout.desktop.model.toPayloadJson
import com.spiritscout.desktop.service.ApiException
import com.spiritscout.desktop.service.BackendHost
import com.spiritscout.desktop.service.RuntimeResolver
import com.spiritscout.desktop.service.SpiritApi
import com.spiritscout.desktop.ui.DesktopI18n
import com.spiritscout.desktop.state.TrafficController
import com.spiritscout.desktop.state.AssetCollectionController
import com.spiritscout.desktop.state.ModelProviderController
import com.spiritscout.desktop.state.SkillController
import com.spiritscout.desktop.state.McpController
import com.spiritscout.desktop.state.ProjectController
import com.spiritscout.desktop.state.BrowserAccountController
import com.spiritscout.desktop.state.ProxyController
import com.spiritscout.desktop.state.ScheduleController
import com.spiritscout.desktop.state.AgentController
import com.spiritscout.desktop.state.LocalToolsController
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.async
import kotlinx.coroutines.cancel
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.swing.Swing
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.jsonObject
import java.nio.file.Files
import java.nio.file.Path
import java.net.URLEncoder
import java.net.URI
import java.awt.Image
import java.awt.RenderingHints
import java.awt.SystemTray
import java.awt.Toolkit
import java.awt.TrayIcon
import java.awt.MenuItem
import java.awt.PopupMenu
import java.awt.datatransfer.DataFlavor
import java.awt.image.BufferedImage
import javax.imageio.ImageIO
import java.nio.charset.StandardCharsets
import java.time.Instant
import java.util.prefs.Preferences

enum class UploadKind {
    FILE,
    FOLDER
}

data class PendingUpload(
    val id: String,
    val name: String,
    val sourcePath: Path? = null,
    val kind: UploadKind = UploadKind.FILE,
    val error: String? = null
)

private fun Image.toBufferedImage(): BufferedImage {
    if (this is BufferedImage) return this
    val width = getWidth(null).coerceAtLeast(1)
    val height = getHeight(null).coerceAtLeast(1)
    return BufferedImage(width, height, BufferedImage.TYPE_INT_ARGB).also { target ->
        val graphics = target.createGraphics()
        try {
            graphics.setRenderingHint(RenderingHints.KEY_INTERPOLATION, RenderingHints.VALUE_INTERPOLATION_BICUBIC)
            graphics.drawImage(this, 0, 0, null)
        } finally {
            graphics.dispose()
        }
    }
}

class AppController {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Swing)
    private val backend = BackendHost()
    private var api: SpiritApi? = null
    val traffic = TrafficController({ api }, scope)
    val assetCollection = AssetCollectionController({ api }, scope)
    val modelProviders = ModelProviderController({ api }, scope)
    val skills = SkillController({ api }, scope)
    val mcp = McpController({ api }, scope)
    val projectCatalog = ProjectController({ api }, scope)
    val browserAccounts = BrowserAccountController({ api }, scope)
    val proxyPool = ProxyController({ api }, scope)
    val schedules = ScheduleController({ api }, scope)
    val agentCatalog = AgentController({ api }, scope)
    val localTools = LocalToolsController({ api }, scope)

    init {
        Runtime.getRuntime().addShutdownHook(
            Thread(
                { runCatching { backend.stopBlocking() } },
                "spiritscout-backend-shutdown"
            )
        )
    }

    var booting by mutableStateOf(true)
        private set
    var bootMessage by mutableStateOf("正在启动灵枢…")
        private set
    var bootError by mutableStateOf<String?>(null)
        private set
    var backendUrl by mutableStateOf("")
        private set
    var runtimeName by mutableStateOf("")
        private set
    var requiresLogin by mutableStateOf(false)
        private set
    var loginError by mutableStateOf<String?>(null)
        private set
    var darkTheme by mutableStateOf(false)
        private set
    var language by mutableStateOf("zh-CN")
        private set
    var motionPreference by mutableStateOf("system")
        private set

    var section by mutableStateOf(Section.DASHBOARD)
        private set
    var selectedSession by mutableStateOf<SessionItem?>(null)
        private set
    var workspace by mutableStateOf<WorkspaceSnapshot?>(null)
        private set
    var workspaceLoading by mutableStateOf(false)
        private set
    var workspaceDraft by mutableStateOf("")
        private set
    var workspaceError by mutableStateOf<String?>(null)
        private set
    var workspaceTab by mutableStateOf(WorkspaceTab.CHAT)
        private set
    var workspaceTabJson by mutableStateOf<JsonElement?>(null)
        private set
    var workspaceTabLoading by mutableStateOf(false)
        private set
    var workspaceTabError by mutableStateOf<String?>(null)
        private set
    private var workspaceEventJob: Job? = null
    private var workspaceEventOffset = 0L
    val sideAgents = mutableStateListOf<SideAgentOption>()
    val sideMessages = mutableStateListOf<SideMessage>()
    val sidePendingApprovals = mutableStateListOf<PendingApprovalItem>()
    val sidePendingQuestions = mutableStateListOf<PendingQuestionItem>()
    var sideActor by mutableStateOf("")
        private set
    var sideTaskId by mutableStateOf("")
        private set
    var sideChildSessionId by mutableStateOf("")
        private set
    var sideDraft by mutableStateOf("")
        private set
    var sideStatus by mutableStateOf("")
        private set
    var sideError by mutableStateOf<String?>(null)
        private set
    var sideBusy by mutableStateOf(false)
        private set
    private var sideRosterLoadedFor by mutableStateOf("")
    private var sideRosterCache = emptyList<SideAgentOption>()

    val sessions = mutableStateListOf<SessionItem>()
    val metrics = mutableStateListOf<MetricItem>()
    val resources = mutableStateMapOf<Section, List<ResourceItem>>()
    val loading = mutableStateMapOf<Section, Boolean>()
    val errors = mutableStateMapOf<Section, String?>()
    val logs = mutableStateListOf<String>()
    val models = mutableStateListOf<String>()
    val pendingUploads = mutableStateListOf<PendingUpload>()
    val failedUploads = mutableStateListOf<PendingUpload>()
    val taskProjects = mutableStateListOf<TaskOption>()
    val taskProxyPlans = mutableStateListOf<TaskOption>()
    val taskBrowserAccounts = mutableStateListOf<TaskOption>()
    val taskAssetCampaigns = mutableStateListOf<TaskOption>()
    val taskAssetTargets = mutableStateListOf<TaskOption>()
    val taskAssetExcludedAssets = mutableStateListOf<String>()
    val assetProviders = mutableStateListOf<AssetProviderItem>()
    var taskOptionsLoading by mutableStateOf(false)
        private set
    var taskCampaignsLoading by mutableStateOf(false)
        private set
    var taskTargetsLoading by mutableStateOf(false)
        private set
    var taskAssetTargetsCampaignId by mutableStateOf("")
        private set
    var taskInitialProjectId by mutableStateOf("")
        private set
    var taskInitialCampaignId by mutableStateOf("")
        private set
    private var taskCampaignRequestSerial = 0
    private var taskTargetRequestSerial = 0
    var assetProvidersLoading by mutableStateOf(false)
        private set
    var assetProvidersError by mutableStateOf<String?>(null)
        private set

    var system by mutableStateOf<SystemResourceSnapshot?>(null)
        private set
    var settingsJson by mutableStateOf<JsonElement?>(null)
        private set
    var updateJson by mutableStateOf<JsonElement?>(null)
        private set
    var updateError by mutableStateOf<String?>(null)
        private set
    var updateBusy by mutableStateOf(false)
        private set
    var storageJson by mutableStateOf<JsonElement?>(null)
        private set
    var storagePreviewJson by mutableStateOf<JsonElement?>(null)
        private set
    var dashboardPeriod by mutableStateOf("today")
        private set
    var showNewTask by mutableStateOf(false)
        private set
    var taskError by mutableStateOf<String?>(null)
        private set
    var uploading by mutableStateOf(false)
        private set
    var showRuleConflict by mutableStateOf(false)
        private set
    var taskRuleConflicts by mutableStateOf<List<String>>(emptyList())
        private set
    private var pendingRuleConflictRequest: NewTaskRequest? = null
    private var pendingRuleConflictCallback: ((SessionItem) -> Unit)? = null
    private var activeUploadOperations = 0
    private val desktopPreferences = Preferences.userNodeForPackage(AppController::class.java)
    var notificationsEnabled by mutableStateOf(true)
        private set
    var notificationJson by mutableStateOf<JsonElement?>(null)
        private set
    var notificationUnread by mutableStateOf(0)
        private set
    var toast by mutableStateOf<String?>(null)
        private set
    var jsonAction by mutableStateOf<JsonActionState?>(null)
        private set
    var jsonActionError by mutableStateOf<String?>(null)
        private set
    var showApiConsole by mutableStateOf(false)
        private set
    var apiConsoleLoading by mutableStateOf(false)
        private set
    var apiConsoleResponse by mutableStateOf("")
        private set
    var apiConsoleError by mutableStateOf<String?>(null)
        private set
    var experienceMergeOpen by mutableStateOf(false)
        private set
    var experienceMergeLoading by mutableStateOf(false)
        private set
    var experienceMergeThreshold by mutableStateOf("90")
        private set
    var experienceMergeCandidates by mutableStateOf("")
        private set
    var experienceMergeIds by mutableStateOf("")
        private set
    var experienceMergeDraft by mutableStateOf("")
        private set
    var experienceMergeToken by mutableStateOf("")
        private set
    var experienceMergeError by mutableStateOf<String?>(null)
        private set

    fun bootstrap() {
        scope.launch {
            try {
                darkTheme = desktopPreferences.getBoolean("dark_theme", false)
                notificationsEnabled = desktopPreferences.getBoolean("notifications_enabled", true)
                language = desktopPreferences.get("language", "zh-CN")
                motionPreference = desktopPreferences.get("motion_preference", "system")
                DesktopI18n.applyLanguage(language)
                DesktopI18n.applyMotionPreference(motionPreference)
                booting = true
                bootError = null
                val runtime = withContext(Dispatchers.IO) {
                    RuntimeResolver.resolve { message ->
                        scope.launch { bootMessage = message }
                    }
                }
                runtimeName = runtime.displayName
                bootMessage = "正在启动本机控制台…"
                withContext(Dispatchers.IO) {
                    backend.start(runtime) { line ->
                        scope.launch {
                            logs.add(line)
                            while (logs.size > 1200) logs.removeAt(0)
                        }
                    }
                }
                backendUrl = backend.baseUrl
                api = SpiritApi(backend.baseUrl)
                bootMessage = "正在加载工作区…"
                try {
                    api?.get("/api/sessions")
                } catch (error: ApiException) {
                    if (error.status == 401 || error.status == 403) {
                        requiresLogin = true
                        bootMessage = "需要管理员登录"
                        booting = false
                        return@launch
                    }
                    throw error
                }
                loadDashboardInternal()
                loadSessionsInternal()
                booting = false
                scope.launch {
                    while (true) {
                        loadNotifications()
                        delay(30_000)
                    }
                }
            } catch (error: Exception) {
                bootError = error.message ?: error.toString()
                booting = false
                logs.add("启动失败：${error.stackTraceToString()}")
            }
        }
    }

    fun navigate(next: Section) {
        stopWorkspaceEventStream()
        section = next
        selectedSession = null
        workspace = null
        workspaceTab = WorkspaceTab.CHAT
        workspaceTabJson = null
        resources[next]?.let { return }
        scope.launch { loadSection(next) }
    }

    fun refreshCurrent() {
        val target = section
        scope.launch {
            when (target) {
                Section.DASHBOARD -> loadDashboardInternal()
                Section.TASKS -> loadSessionsInternal()
                Section.SETTINGS -> loadSystemInternal()
                Section.WORKSPACE -> refreshWorkspaceInternal()
                else -> loadSection(target)
            }
        }
    }

    fun selectWorkspaceTab(tab: WorkspaceTab) {
        workspaceTab = tab
        workspaceTabJson = null
        workspaceTabError = null
        if (tab == WorkspaceTab.CHAT) return
        scope.launch { loadWorkspaceTabInternal(tab) }
    }

    fun openSession(session: SessionItem) {
        stopWorkspaceEventStream()
        selectedSession = session
        section = Section.WORKSPACE
        workspace = null
        workspaceTab = WorkspaceTab.CHAT
        workspaceTabJson = null
        workspaceError = null
        traffic.reset()
        clearSideChat()
        scope.launch { refreshWorkspaceInternal() }
        startWorkspaceEventStream(session.id)
    }

    fun returnToTasks() {
        stopWorkspaceEventStream()
        section = Section.TASKS
        selectedSession = null
        workspace = null
        traffic.reset()
        clearSideChat()
        scope.launch { loadSessionsInternal() }
    }

    fun openNewTask() {
        taskInitialProjectId = ""
        taskInitialCampaignId = ""
        taskError = null
        pendingUploads.clear()
        failedUploads.clear()
        pendingRuleConflictRequest = null
        pendingRuleConflictCallback = null
        taskRuleConflicts = emptyList()
        showRuleConflict = false
        taskAssetCampaigns.clear()
        taskAssetTargets.clear()
        taskAssetExcludedAssets.clear()
        taskAssetTargetsCampaignId = ""
        taskCampaignsLoading = false
        taskTargetsLoading = false
        showNewTask = true
        scope.launch {
            loadModelsInternal()
            loadTaskOptionsInternal()
        }
    }

    fun openNewTaskForAssets(projectId: String, campaignId: String) {
        openNewTask()
        taskInitialProjectId = projectId
        taskInitialCampaignId = campaignId
    }

    fun closeNewTask() {
        showNewTask = false
        showRuleConflict = false
        pendingRuleConflictRequest = null
        pendingRuleConflictCallback = null
        taskRuleConflicts = emptyList()
        taskError = null
    }

    fun setDraft(value: String) {
        workspaceDraft = value
    }

    fun sendWorkspaceMessage() {
        val content = workspaceDraft.trim()
        val currentApi = api ?: return
        val current = selectedSession ?: return
        if (content.isBlank() && pendingUploads.isEmpty()) return
        workspaceDraft = ""
        scope.launch {
            try {
                currentApi.postMessage(current.id, content, pendingUploads.map { it.id })
                pendingUploads.clear()
                workspace = workspace?.copy(
                    timeline = workspace!!.timeline + TimelineItem("你", content, TimelineKind.USER)
                )
                toast = "消息已发送"
                refreshWorkspaceInternal()
            } catch (error: Exception) {
                workspaceError = error.message
            }
        }
    }

    fun sessionAction(action: String) {
        val currentApi = api ?: return
        val current = selectedSession ?: return
        scope.launch {
            try {
                currentApi.post("/api/sessions/${current.id}/$action")
                refreshWorkspaceInternal()
                loadSessionsInternal()
            } catch (error: Exception) {
                workspaceError = error.message
            }
        }
    }

    fun distillSessionExperience() {
        val currentApi = api ?: return
        val current = selectedSession ?: return
        scope.launch {
            try {
                workspaceTabError = null
                currentApi.post("/api/sessions/${url(current.id)}/experience/distill")
                toast = "经验提炼已启动"
                loadWorkspaceTabInternal(WorkspaceTab.EXPERIENCE)
            } catch (error: Exception) {
                workspaceTabError = error.message
            }
        }
    }

    fun changeSessionModel() {
        val current = selectedSession ?: return
        openJsonAction(
            JsonActionState(
                title = "切换会话模型",
                description = "填写模型名称；留空由后端规则处理。",
                initialJson = """{"model":"${current.model.takeIf { it != "自动" }.orEmpty()}"}""",
                method = "POST",
                pathTemplate = "/api/sessions/${url(current.id)}/model",
                reloadSection = Section.WORKSPACE,
                successMessage = "会话模型已更新"
            )
        )
    }

    fun openSessionManageAction(operation: String) {
        val current = selectedSession ?: return
        val sid = url(current.id)
        val action = when (operation) {
            "rename" -> JsonActionState(
                title = "重命名会话",
                description = "清空标题可恢复自动命名。",
                initialJson = prettyJson.encodeToString(
                    JsonElement.serializer(),
                    buildJsonObject { put("title", current.title) }
                ),
                method = "PATCH",
                pathTemplate = "/api/sessions/$sid",
                reloadSection = Section.WORKSPACE,
                successMessage = "会话已重命名"
            )
            "project" -> JsonActionState(
                title = "切换会话项目",
                description = "填写项目 ID；空字符串表示移到未分类。",
                initialJson = """{"project_id":""}""",
                method = "PATCH",
                pathTemplate = "/api/sessions/$sid",
                reloadSection = Section.WORKSPACE,
                successMessage = "会话项目已更新"
            )
            else -> JsonActionState(
                title = "删除会话",
                description = "确认删除会话记录、工作区和交付文件。",
                method = "DELETE",
                pathTemplate = "/api/sessions/$sid?confirm=true",
                reloadSection = Section.TASKS,
                navigateOnSuccess = true,
                successMessage = "会话已删除"
            )
        }
        openJsonAction(action)
    }

    fun loadSessionProjectOptions() {
        val currentApi = api ?: return
        scope.launch {
            try {
                taskProjects.clear()
                taskProjects += currentApi.get("/api/projects").array("projects")
                    .map { it.objectOrEmpty() }
                    .filter { it.string("project_id").isNotBlank() && !it.boolean("read_only") }
                    .map {
                        TaskOption(
                            id = it.string("project_id"),
                            label = it.string("name").ifBlank { it.string("project_id") }
                        )
                    }
            } catch (error: Exception) {
                toast = "读取项目失败：${error.message}"
            }
        }
    }

    fun renameSelectedSession(title: String, onDone: () -> Unit) {
        val currentApi = api ?: return
        val current = selectedSession ?: return
        scope.launch {
            try {
                currentApi.patch(
                    "/api/sessions/${url(current.id)}",
                    buildJsonObject { put("title", title.trim()) }.toString()
                )
                toast = "会话已重命名"
                onDone()
                refreshWorkspaceInternal()
                loadSessionsInternal()
            } catch (error: Exception) {
                toast = "重命名失败：${error.message}"
            }
        }
    }

    fun moveSelectedSession(projectId: String, onDone: () -> Unit) {
        val currentApi = api ?: return
        val current = selectedSession ?: return
        scope.launch {
            try {
                currentApi.patch(
                    "/api/sessions/${url(current.id)}",
                    buildJsonObject { put("project_id", projectId) }.toString()
                )
                toast = if (projectId.isBlank()) "会话已移到未分类" else "会话项目已更新"
                onDone()
                refreshWorkspaceInternal()
                loadSessionsInternal()
            } catch (error: Exception) {
                toast = "移动会话失败：${error.message}"
            }
        }
    }

    fun deleteSelectedSession(onDone: () -> Unit) {
        val currentApi = api ?: return
        val current = selectedSession ?: return
        scope.launch {
            try {
                currentApi.delete("/api/sessions/${url(current.id)}?confirm=true")
                toast = "会话已删除"
                onDone()
                returnToTasks()
            } catch (error: Exception) {
                toast = "删除会话失败：${error.message}"
            }
        }
    }

    fun decideApproval(approvalId: String, allow: Boolean) {
        val currentApi = api ?: return
        val current = selectedSession ?: return
        scope.launch {
            try {
                currentApi.post(
                    "/api/sessions/${url(current.id)}/approvals/${url(approvalId)}",
                    buildJsonObject { put("allow", allow) }.toString()
                )
                toast = if (allow) "已允许本次调用" else "已拒绝本次调用"
                refreshWorkspaceInternal()
            } catch (error: Exception) {
                workspaceError = error.message
            }
        }
    }

    fun answerQuestion(questionId: String, choice: Int? = null) {
        val currentApi = api ?: return
        val current = selectedSession ?: return
        if (choice != null) {
            scope.launch {
                try {
                    currentApi.post(
                        "/api/sessions/${url(current.id)}/questions/${url(questionId)}",
                        buildJsonObject { put("choice", choice) }.toString()
                    )
                    toast = "已提交答复"
                    refreshWorkspaceInternal()
                } catch (error: Exception) {
                    workspaceError = error.message
                }
            }
            return
        }
        openJsonAction(
            JsonActionState(
                title = "回答智能体提问",
                description = "可用 text 回答，或按题目要求提交 choices 数组。",
                initialJson = """{"text":""}""",
                method = "POST",
                pathTemplate = "/api/sessions/${url(current.id)}/questions/${url(questionId)}",
                reloadSection = Section.WORKSPACE,
                successMessage = "答复已提交"
            )
        )
    }

    fun selectSideAgent(actor: String) {
        sideActor = actor
        sideError = null
        sideMessages.clear()
        sidePendingApprovals.clear()
        sidePendingQuestions.clear()
        sideChildSessionId = ""
        sideTaskId = ""
        sideStatus = ""
        if (actor.isBlank()) return
        val parent = selectedSession ?: return
        val child = sessions.firstOrNull {
            it.sideParentId == parent.id && it.sideAgent == actor
        }
        if (child != null) {
            sideChildSessionId = child.id
            sideTaskId = child.sideTaskId
            sideStatus = child.status
            refreshSideChat()
        }
    }

    fun setSideTask(taskId: String) {
        if (sideChildSessionId.isBlank()) sideTaskId = taskId
    }

    fun updateSideDraft(value: String) {
        sideDraft = value
    }

    fun sendSideMessage() {
        val currentApi = api ?: return
        val parent = selectedSession ?: return
        val mission = sideDraft.trim()
        if (sideActor.isBlank() || mission.isBlank() || sideBusy) return
        if (sideChildSessionId.isBlank() && pendingUploads.isNotEmpty()) {
            sideError = "首次旁路对话创建后再添加附件。"
            return
        }
        val childSession = sideChildSessionId
        scope.launch {
            sideBusy = true
            sideError = null
            sideStatus = "running"
            try {
                val child = if (childSession.isBlank()) {
                    val payload = buildJsonObject {
                        put("actor", sideActor)
                        put("task_id", sideTaskId)
                        put("mission", mission)
                    }
                    val created = currentApi.post(
                        "/api/sessions/${url(parent.id)}/agent-sessions",
                        payload.toString()
                    )
                    SessionItem.fromJson(created).also {
                        sideChildSessionId = it.id
                        sideTaskId = it.sideTaskId.ifBlank { sideTaskId }
                    }
                } else {
                    currentApi.postMessage(
                        childSession,
                        mission,
                        pendingUploads.map { it.id }
                    )
                    sessions.firstOrNull { it.id == childSession }
                        ?: SessionItem.fromJson(
                            currentApi.get("/api/sessions/${url(childSession)}")
                        )
                }
                sideMessages += SideMessage("user", mission)
                sideDraft = ""
                sideStatus = child.status.ifBlank { "running" }
                pendingUploads.clear()
                failedUploads.clear()
                loadSessionsInternal()
                refreshSideChat()
            } catch (error: Exception) {
                sideError = error.message ?: "旁路消息发送失败"
                sideStatus = "failed"
            } finally {
                sideBusy = false
            }
        }
    }

    fun refreshSideChat() {
        val currentApi = api ?: return
        val child = sideChildSessionId
        if (child.isBlank()) return
        scope.launch {
            try {
                val root = currentApi.get("/api/sessions/${url(child)}/conversation")
                    .objectOrEmpty()
                sideMessages.clear()
                root.array("messages").forEach { raw ->
                    val item = raw.objectOrEmpty()
                    val role = item.string("role")
                    if (role !in setOf("user", "assistant", "agent")) return@forEach
                    val content = item.string("content")
                        .ifBlank { item.string("text") }
                        .ifBlank { item.string("detail") }
                    if (content.isNotBlank()) {
                        sideMessages += SideMessage(
                            if (role == "user") "user" else "assistant",
                            content
                        )
                    }
                }
                val session = root.element("session")?.objectOrEmpty()
                sideStatus = session?.string("status").orEmpty()
                sideError = session?.string("error").takeIf { !it.isNullOrBlank() }
                sidePendingApprovals.clear()
                sidePendingApprovals += root.array("pending_approvals").map { raw ->
                    val item = raw.objectOrEmpty()
                    PendingApprovalItem(
                        id = item.string("approval_id").ifBlank { item.string("id") },
                        action = item.string("action"),
                        purpose = item.string("purpose").ifBlank { item.string("detail") },
                        detail = item.string("detail")
                    )
                }
                sidePendingQuestions.clear()
                sidePendingQuestions += root.array("pending_questions").map { raw ->
                    val item = raw.objectOrEmpty()
                    PendingQuestionItem(
                        id = item.string("question_id").ifBlank { item.string("id") },
                        agent = item.string("agent").ifBlank { sideActor },
                        question = item.string("question"),
                        options = item.array("options").map { it.toString().trim('"') },
                        multiple = item.boolean("multiple"),
                        secret = item.boolean("secret"),
                        rawJson = pretty(raw)
                    )
                }
            } catch (error: Exception) {
                sideError = error.message
            }
        }
    }

    fun decideSideApproval(approvalId: String, allow: Boolean) {
        val currentApi = api ?: return
        val child = sideChildSessionId
        if (child.isBlank()) return
        scope.launch {
            try {
                currentApi.post(
                    "/api/sessions/${url(child)}/approvals/${url(approvalId)}",
                    buildJsonObject { put("allow", allow) }.toString()
                )
                refreshSideChat()
            } catch (error: Exception) {
                sideError = error.message
            }
        }
    }

    fun answerSideQuestion(questionId: String, choice: Int? = null, text: String = "") {
        val currentApi = api ?: return
        val child = sideChildSessionId
        if (child.isBlank()) return
        scope.launch {
            try {
                val payload = if (choice != null) {
                    buildJsonObject { put("choice", choice) }
                } else {
                    buildJsonObject { put("text", text.trim()) }
                }
                currentApi.post(
                    "/api/sessions/${url(child)}/questions/${url(questionId)}",
                    payload.toString()
                )
                refreshSideChat()
            } catch (error: Exception) {
                sideError = error.message
            }
        }
    }

    fun openSideChildSession() {
        val child = sessions.firstOrNull { it.id == sideChildSessionId } ?: return
        openSession(child)
    }

    fun returnToSideParent() {
        val parentId = selectedSession?.sideParentId.orEmpty()
        val parent = sessions.firstOrNull { it.id == parentId } ?: return
        openSession(parent)
    }

    private fun clearSideChat() {
        sideAgents.clear()
        sideMessages.clear()
        sidePendingApprovals.clear()
        sidePendingQuestions.clear()
        sideActor = ""
        sideTaskId = ""
        sideChildSessionId = ""
        sideDraft = ""
        sideStatus = ""
        sideError = null
        sideBusy = false
        sideRosterLoadedFor = ""
        sideRosterCache = emptyList()
    }

    fun stopBackgroundTask(jobId: String) {
        val currentApi = api ?: return
        val current = selectedSession ?: return
        scope.launch {
            try {
                currentApi.post(
                    "/api/sessions/${url(current.id)}/background-tasks/${url(jobId)}/stop"
                )
                toast = "后台任务已停止"
                loadWorkspaceTabInternal(WorkspaceTab.BACKGROUND)
            } catch (error: Exception) {
                workspaceTabError = error.message
            }
        }
    }

    fun openBackendUrl(path: String) {
        val url = backendUrl.trimEnd('/') + "/" + path.trimStart('/')
        runCatching { java.awt.Desktop.getDesktop().browse(URI.create(url)) }
            .onFailure { toast = "无法打开链接：${it.message}" }
    }

    fun openTrafficSession(item: ResourceItem) {
        val currentApi = api ?: return
        val sid = item.id
        if (sid.isBlank()) return
        scope.launch {
            try {
                val detail = currentApi.get("/api/sessions/${url(sid)}")
                openSession(SessionItem.fromJson(detail))
                selectWorkspaceTab(WorkspaceTab.TRAFFIC)
            } catch (error: Exception) {
                toast = error.message
            }
        }
    }

    fun createTask(request: NewTaskRequest, onCreated: (SessionItem) -> Unit) {
        val currentApi = api ?: return
        scope.launch {
            try {
                taskError = null
                val payload = request.toPayloadJson(pendingUploads.map { it.id })
                val result = currentApi.post("/api/sessions", payload.toString())
                val created = SessionItem.fromJson(result)
                showNewTask = false
                showRuleConflict = false
                pendingRuleConflictRequest = null
                pendingRuleConflictCallback = null
                taskRuleConflicts = emptyList()
                loadSessionsInternal()
                onCreated(created)
            } catch (error: Exception) {
                val conflicts = ruleConflicts(error)
                if (conflicts != null) {
                    pendingRuleConflictRequest = request
                    pendingRuleConflictCallback = onCreated
                    taskRuleConflicts = conflicts
                    showRuleConflict = true
                    taskError = null
                } else {
                    taskError = error.message ?: "创建任务失败"
                }
            }
        }
    }

    fun confirmRuleConflicts() {
        val request = pendingRuleConflictRequest ?: return
        val callback = pendingRuleConflictCallback ?: return
        showRuleConflict = false
        taskRuleConflicts = emptyList()
        createTask(request.copy(acceptRuleConflicts = true), callback)
    }

    fun cancelRuleConflicts() {
        showRuleConflict = false
        taskRuleConflicts = emptyList()
        pendingRuleConflictRequest = null
        pendingRuleConflictCallback = null
    }

    private fun ruleConflicts(error: Exception): List<String>? {
        if (error !is ApiException || error.status != 422 || error.body.isBlank()) return null
        return runCatching {
            val detail = Json.parseToJsonElement(error.body)
                .objectOrEmpty()
                .element("detail")
                ?.objectOrEmpty()
                ?: return@runCatching null
            if (detail.string("code") != "rule_conflict") return@runCatching null
            val conflicts = detail.array("conflicts").map { it.toString().trim('"') }
                .filter { it.isNotBlank() }
            conflicts.ifEmpty {
                listOf(detail.string("message").ifBlank { "任务规则存在冲突，需要确认后继续。" })
            }
        }.getOrNull()
    }

    fun addUploads(paths: List<Path>) {
        val currentApi = api ?: return
        if (paths.isEmpty()) return
        uploadPaths(currentApi, paths)
    }

    fun addFolderUploads(root: Path) {
        val currentApi = api ?: return
        scope.launch {
            beginUpload()
            taskError = null
            try {
                val id = currentApi.uploadFolder(root.toAbsolutePath().normalize())
                pendingUploads += PendingUpload(
                    id,
                    root.fileName.toString(),
                    root.toAbsolutePath().normalize(),
                    UploadKind.FOLDER
                )
            } catch (error: Exception) {
                taskError = "文件夹上传失败：${error.message}"
                failedUploads += failedUpload(
                    root.fileName.toString(),
                    root.toAbsolutePath().normalize(),
                    UploadKind.FOLDER,
                    error
                )
            } finally {
                endUpload()
            }
        }
    }

    fun addClipboardImage() {
        try {
            val clipboard = Toolkit.getDefaultToolkit().systemClipboard
            if (!clipboard.isDataFlavorAvailable(DataFlavor.imageFlavor)) {
                taskError = "剪贴板中没有可上传的图片"
                return
            }
            val image = clipboard.getData(DataFlavor.imageFlavor) as? Image
                ?: throw IllegalArgumentException("剪贴板图片格式不受支持")
            val path = Files.createTempFile("spiritscout-clipboard-", ".png")
            path.toFile().deleteOnExit()
            if (!ImageIO.write(image.toBufferedImage(), "png", path.toFile())) {
                Files.deleteIfExists(path)
                throw IllegalStateException("无法编码剪贴板图片")
            }
            addUploads(listOf(path))
        } catch (error: Exception) {
            taskError = "读取剪贴板图片失败：${error.message}"
        }
    }

    fun loadTaskAssetCampaigns(projectId: String) {
        val currentApi = api ?: return
        val requestSerial = ++taskCampaignRequestSerial
        taskAssetCampaigns.clear()
        taskAssetTargets.clear()
        taskAssetExcludedAssets.clear()
        taskAssetTargetsCampaignId = ""
        if (projectId.isBlank()) {
            taskCampaignsLoading = false
            return
        }
        scope.launch {
            taskCampaignsLoading = true
            try {
                val result = currentApi.get("/api/projects/${url(projectId)}/asset-campaigns")
                if (requestSerial != taskCampaignRequestSerial) return@launch
                val campaigns = result.array("campaigns")
                    .filter {
                        it.objectOrEmpty().string("status") in setOf(
                            "completed", "completed_with_errors", "stopped", "failed"
                        )
                    }
                    .filter {
                        it.objectOrEmpty().element("stats")?.objectOrEmpty()?.int("candidates") != 0
                    }
                    .map {
                        val item = it.objectOrEmpty()
                        val candidates = item.element("stats")?.objectOrEmpty()?.int("candidates") ?: 0
                        TaskOption(
                            id = item.string("campaign_id"),
                            label = item.array("targets").joinToString("、") {
                                target -> target.toString().trim('"')
                            }.ifBlank { item.string("campaign_id") },
                            detail = "${item.string("status")} · $candidates 个资产"
                        )
                    }
                taskAssetCampaigns += campaigns
            } catch (error: Exception) {
                if (requestSerial == taskCampaignRequestSerial) {
                    taskError = "读取资产采集批次失败：${error.message}"
                }
            } finally {
                if (requestSerial == taskCampaignRequestSerial) taskCampaignsLoading = false
            }
        }
    }

    fun loadTaskAssetTargets(campaignId: String) {
        val currentApi = api ?: return
        val requestSerial = ++taskTargetRequestSerial
        taskAssetTargets.clear()
        taskAssetExcludedAssets.clear()
        taskAssetTargetsCampaignId = ""
        if (campaignId.isBlank()) {
            taskTargetsLoading = false
            return
        }
        scope.launch {
            taskTargetsLoading = true
            try {
                val result = currentApi.get("/api/asset-campaigns/${url(campaignId)}/targets")
                if (requestSerial != taskTargetRequestSerial) return@launch
                taskAssetTargets += result.array("targets").mapNotNull {
                    val item = it.objectOrEmpty()
                    val value = item.string("value")
                    if (value.isBlank()) null else TaskOption(
                        id = value,
                        label = item.string("title").ifBlank { value },
                        detail = listOf(
                            item.string("verification_status").ifBlank { "待验证" },
                            item.string("http_status").let { code ->
                                if (code.isBlank()) "" else "HTTP $code"
                            },
                            item.string("egress_name").ifBlank { "历史出口未知" }
                        ).filter { value -> value.isNotBlank() }.joinToString(" · "),
                        selectedByDefault = item.string("verification_status") in
                            setOf("http_responded", "http_verified", "dns_resolved")
                    )
                }
                taskAssetExcludedAssets += result.array("excluded_assets")
                    .map { it.toString().trim('"') }
                    .filter { it.isNotBlank() }
                taskAssetTargetsCampaignId = campaignId
            } catch (error: Exception) {
                if (requestSerial == taskTargetRequestSerial) {
                    taskError = "读取资产列表失败：${error.message}"
                }
            } finally {
                if (requestSerial == taskTargetRequestSerial) taskTargetsLoading = false
            }
        }
    }

    private fun uploadPaths(currentApi: SpiritApi, paths: List<Path>) {
        scope.launch {
            beginUpload()
            taskError = null
            try {
                paths.forEach { path ->
                    try {
                        val id = currentApi.upload(path)
                        pendingUploads += PendingUpload(
                            id,
                            path.fileName.toString(),
                            path.toAbsolutePath().normalize(),
                            UploadKind.FILE
                        )
                    } catch (error: Exception) {
                        failedUploads += failedUpload(
                            path.fileName.toString(),
                            path.toAbsolutePath().normalize(),
                            UploadKind.FILE,
                            error
                        )
                    }
                }
                if (failedUploads.isNotEmpty()) {
                    taskError = "部分附件上传失败，可在附件列表点击重试。"
                }
            } finally {
                endUpload()
            }
        }
    }

    private fun beginUpload() {
        activeUploadOperations += 1
        uploading = true
    }

    private fun endUpload() {
        activeUploadOperations = (activeUploadOperations - 1).coerceAtLeast(0)
        uploading = activeUploadOperations > 0
    }

    private fun failedUpload(
        name: String,
        path: Path,
        kind: UploadKind,
        error: Exception
    ) = PendingUpload(
        id = "failed-${System.nanoTime()}",
        name = name,
        sourcePath = path,
        kind = kind,
        error = error.message ?: "上传失败"
    )

    fun retryUpload(id: String) {
        val failed = failedUploads.firstOrNull { it.id == id } ?: return
        val path = failed.sourcePath ?: return
        failedUploads.removeAll { it.id == id }
        when (failed.kind) {
            UploadKind.FILE -> addUploads(listOf(path))
            UploadKind.FOLDER -> addFolderUploads(path)
        }
    }

    private suspend fun loadTaskOptionsInternal() {
        val currentApi = api ?: return
        taskOptionsLoading = true
        try {
            val (projects, proxies, accounts) = coroutineScope {
                val projectsRequest = async { currentApi.get("/api/projects").array("projects") }
                val proxiesRequest = async { currentApi.get("/api/proxies") }
                val accountsRequest = async { currentApi.get("/api/browser-accounts").array("items") }
                Triple(projectsRequest.await(), proxiesRequest.await(), accountsRequest.await())
            }
            taskProjects.clear()
            taskProjects += projects.map {
                val item = it.objectOrEmpty()
                TaskOption(
                    id = item.string("project_id"),
                    label = item.string("name").ifBlank { item.string("project_id") },
                    detail = item.string("description")
                )
            }
            taskProxyPlans.clear()
            taskProxyPlans += proxies.array("plans").map {
                val item = it.objectOrEmpty()
                TaskOption(
                    id = item.string("id"),
                    label = item.string("name").ifBlank { item.string("id") }
                )
            }
            taskBrowserAccounts.clear()
            taskBrowserAccounts += accounts.map {
                val item = it.objectOrEmpty()
                TaskOption(
                    id = item.string("id"),
                    label = item.string("name").ifBlank { item.string("id") },
                    detail = item.string("role")
                )
            }
        } catch (error: Exception) {
            taskError = "读取任务选项失败：${error.message}"
        } finally {
            taskOptionsLoading = false
        }
    }

    fun removeUpload(id: String) {
        pendingUploads.removeAll { it.id == id }
    }

    fun clearUploads() {
        pendingUploads.clear()
    }

    fun clearToast() {
        toast = null
    }

    fun openApiConsole() {
        apiConsoleError = null
        apiConsoleResponse = ""
        showApiConsole = true
    }

    fun closeApiConsole() {
        showApiConsole = false
        apiConsoleError = null
    }

    fun executeApiConsole(method: String, path: String, body: String) {
        val currentApi = api ?: return
        if (path.isBlank()) {
            apiConsoleError = "API 路径不能为空。"
            return
        }
        scope.launch {
            apiConsoleLoading = true
            apiConsoleError = null
            apiConsoleResponse = ""
            try {
                if (body.isNotBlank() && method.uppercase() != "DELETE") {
                    Json.parseToJsonElement(body)
                }
                val result = when (method.uppercase()) {
                    "GET" -> currentApi.get(path)
                    "POST" -> currentApi.post(path, body.ifBlank { "{}" })
                    "PUT" -> currentApi.put(path, body.ifBlank { "{}" })
                    "PATCH" -> currentApi.patch(path, body.ifBlank { "{}" })
                    "DELETE" -> currentApi.delete(path)
                    else -> error("不支持的 HTTP 方法")
                }
                apiConsoleResponse = pretty(result)
            } catch (error: Exception) {
                apiConsoleError = error.message ?: "请求失败"
            } finally {
                apiConsoleLoading = false
            }
        }
    }

    fun openJsonAction(action: JsonActionState) {
        jsonActionError = null
        jsonAction = action
    }

    fun closeJsonAction() {
        jsonAction = null
        jsonActionError = null
    }

    fun submitJsonAction(identifier: String, text: String) {
        val action = jsonAction ?: return
        val currentApi = api ?: return
        scope.launch {
            try {
                jsonActionError = null
                val id = identifier.trim()
                if (action.requiresId && id.isBlank()) {
                    throw IllegalArgumentException("请填写唯一标识。")
                }
                if (text.isNotBlank() && action.method != "DELETE") {
                    Json.parseToJsonElement(text)
                }
                val path = action.pathTemplate.replace(
                    "{id}",
                    URLEncoder.encode(id, StandardCharsets.UTF_8)
                )
                var result = when (action.method.uppercase()) {
                    "POST" -> currentApi.post(path, if (text.isBlank()) "{}" else text)
                    "PUT" -> currentApi.put(path, if (text.isBlank()) "{}" else text)
                    "PATCH" -> currentApi.patch(path, if (text.isBlank()) "{}" else text)
                    "DELETE" -> currentApi.delete(path)
                    else -> throw IllegalArgumentException("不支持的请求方法：${action.method}")
                }
                if (action.followUpMethod != null && action.followUpPathTemplate != null) {
                    val followId = result.objectOrEmpty().string(action.followUpIdField)
                    if (followId.isBlank()) {
                        throw IllegalStateException("后续操作缺少响应字段 ${action.followUpIdField}")
                    }
                    val followPath = action.followUpPathTemplate.replace("{campaign_id}", url(followId))
                    result = when (action.followUpMethod.uppercase()) {
                        "POST" -> currentApi.post(followPath, "{}")
                        "PUT" -> currentApi.put(followPath, "{}")
                        "PATCH" -> currentApi.patch(followPath, "{}")
                        "DELETE" -> currentApi.delete(followPath)
                        else -> result
                    }
                }
                val reload = action.reloadSection
                jsonAction = null
                toast = action.successMessage
                if (reload != null) {
                    resources.remove(reload)
                    if (section == reload) {
                        loadSection(reload)
                    } else if (action.navigateOnSuccess) {
                        navigate(reload)
                    }
                }
            } catch (error: Exception) {
                jsonActionError = error.message ?: "操作失败"
            }
        }
    }

    fun openResourceAction(target: Section, item: ResourceItem?, operation: String) {
        val currentApi = api ?: return
        scope.launch {
            try {
                val action = when (target) {
                    Section.SKILLS -> buildSkillAction(currentApi, item, operation)
                    Section.MCP -> buildMcpAction(item, operation)
                    Section.AGENTS -> buildAgentAction(item, operation)
                    Section.MODELS -> buildModelAction(item, operation)
                    Section.PROJECTS -> buildProjectAction(item, operation)
                    Section.SCHEDULES -> buildScheduleAction(item, operation)
                    Section.BROWSER_ACCOUNTS -> buildBrowserAccountAction(item, operation)
                    Section.EXPERIENCE -> buildExperienceAction(item, operation)
                    Section.LOCAL_TOOLS -> buildLocalToolsAction(currentApi)
                    else -> null
                }
                if (action == null) {
                    toast = "该模块暂不支持此操作"
                } else {
                    openJsonAction(action)
                }
            } catch (error: Exception) {
                toast = error.message ?: "读取配置失败"
            }
        }
    }

    fun openProviderAction() {
        openJsonAction(
            JsonActionState(
                title = "添加模型供应商",
                description = "填写供应商协议、API 地址和密钥。密钥只在保存时提交。",
                initialJson = """{"name":"","provider":"openai_compatible","base_url":"","api_format":"auto","api_key_value":"","billing_scheme":"","billing_plan":""}""",
                method = "POST",
                pathTemplate = "/api/providers",
                reloadSection = Section.MODELS,
                successMessage = "供应商已保存"
            )
        )
    }

    fun openAssetCampaignAction() {
        openJsonAction(
            JsonActionState(
                title = "新建资产采集",
                description = "填写项目 ID、目标列表和排除资产；创建后会自动开始采集。",
                initialJson = """{"targets":[],"excluded_assets":[],"oneforall_path":"","brute":false}""",
                method = "POST",
                pathTemplate = "/api/projects/{id}/asset-campaigns",
                requiresId = true,
                idLabel = "项目 ID",
                reloadSection = Section.ASSETS,
                followUpMethod = "POST",
                followUpPathTemplate = "/api/asset-campaigns/{campaign_id}/start",
                followUpIdField = "campaign_id",
                successMessage = "资产采集已创建并启动"
            )
        )
    }

    fun toggleSchedule(id: String, enabled: Boolean) {
        val currentApi = api ?: return
        scope.launch {
            try {
                currentApi.patch("/api/schedules/${url(id)}", buildJsonObject { put("enabled", enabled) }.toString())
                toast = if (enabled) "自动任务已启用" else "自动任务已停用"
                resources.remove(Section.SCHEDULES)
                loadSection(Section.SCHEDULES)
            } catch (error: Exception) {
                toast = error.message
            }
        }
    }

    fun browserAccountAction(item: ResourceItem, action: String) {
        val currentApi = api ?: return
        val version = versionOf(item)
        scope.launch {
            try {
                currentApi.post(
                    "/api/browser-accounts/${url(item.id)}/${url(action)}",
                    buildJsonObject { put("expected_version", version) }.toString()
                )
                toast = when (action) {
                    "open" -> "已打开登录窗口"
                    "capture" -> "登录态已保存"
                    "clear" -> "账号缓存已清理"
                    else -> "操作已完成"
                }
                resources.remove(Section.BROWSER_ACCOUNTS)
                loadSection(Section.BROWSER_ACCOUNTS)
            } catch (error: Exception) {
                toast = error.message
            }
        }
    }

    fun localToolsAction(action: String) {
        val currentApi = api ?: return
        scope.launch {
            try {
                currentApi.post("/api/local-tools/${url(action)}", "{}")
                toast = when (action) {
                    "refresh" -> "本地工具索引已刷新"
                    "cleanup" -> "本地工具暂存已清理"
                    else -> "操作已完成"
                }
                resources.remove(Section.LOCAL_TOOLS)
                loadSection(Section.LOCAL_TOOLS)
            } catch (error: Exception) {
                toast = error.message
            }
        }
    }

    fun testModel(item: ResourceItem) {
        val currentApi = api ?: return
        scope.launch {
            try {
                val result = currentApi.post(
                    "/api/models/test",
                    buildJsonObject { put("model", item.id) }.toString()
                )
                toast = "模型测试完成：${result.toString().take(180)}"
            } catch (error: Exception) {
                toast = "模型测试失败：${error.message}"
            }
        }
    }

    fun importSkillArchive(path: Path) {
        val currentApi = api ?: return
        scope.launch {
            try {
                Files.newInputStream(path).use { stream ->
                    currentApi.postRawAsync(
                        "/api/resources/skills/import",
                        stream,
                        "application/octet-stream"
                    )
                }
                toast = "Skill 压缩包已导入"
                resources.remove(Section.SKILLS)
                loadSection(Section.SKILLS)
            } catch (error: Exception) {
                toast = "Skill 导入失败：${error.message}"
            }
        }
    }

    fun restoreExperience(item: ResourceItem) {
        val currentApi = api ?: return
        scope.launch {
            try {
                currentApi.post(
                    "/api/experience/merge/restore",
                    buildJsonObject { put("merged_id", item.id) }.toString()
                )
                toast = "已撤销经验整理"
                resources.remove(Section.EXPERIENCE)
                loadSection(Section.EXPERIENCE)
            } catch (error: Exception) {
                toast = error.message
            }
        }
    }

    fun deleteExperience(item: ResourceItem) {
        val currentApi = api ?: return
        scope.launch {
            try {
                currentApi.delete("/api/experience/${url(item.id)}")
                toast = "经验记录已删除"
                resources.remove(Section.EXPERIENCE)
                loadSection(Section.EXPERIENCE)
            } catch (error: Exception) {
                toast = error.message
            }
        }
    }

    fun openExperienceSource(item: ResourceItem) {
        val currentApi = api ?: return
        val sessionId = runCatching {
            Json.parseToJsonElement(item.rawJson).objectOrEmpty().string("source_session")
        }.getOrDefault("")
        if (sessionId.isBlank()) {
            toast = "这条经验没有记录来源会话"
            return
        }
        scope.launch {
            try {
                val detail = currentApi.get("/api/sessions/${url(sessionId)}")
                openSession(SessionItem.fromJson(detail))
            } catch (error: Exception) {
                toast = error.message
            }
        }
    }

    fun openExperienceTools() {
        val path = Path.of(System.getProperty("user.dir"), "tools", "experience-export")
        if (!Files.isDirectory(path)) {
            toast = "当前安装没有附带经验快照工具目录"
            return
        }
        runCatching { java.awt.Desktop.getDesktop().open(path.toFile()) }
            .onFailure { toast = "无法打开经验工具目录：${it.message}" }
    }

    fun openExperienceMerge() {
        experienceMergeOpen = true
        experienceMergeError = null
        experienceMergeDraft = ""
        experienceMergeToken = ""
        loadExperienceMergeCandidates()
    }

    fun closeExperienceMerge() {
        experienceMergeOpen = false
        experienceMergeError = null
    }

    fun updateExperienceMergeThreshold(value: String) {
        experienceMergeThreshold = value
    }

    fun updateExperienceMergeIds(value: String) {
        experienceMergeIds = value
    }

    fun loadExperienceMergeCandidates() {
        val currentApi = api ?: return
        val threshold = experienceMergeThreshold.toIntOrNull()?.coerceIn(50, 100) ?: 90
        experienceMergeThreshold = threshold.toString()
        scope.launch {
            try {
                experienceMergeLoading = true
                experienceMergeError = null
                val data = currentApi.get(
                    "/api/experience/merge/candidates?threshold=${threshold / 100.0}"
                )
                experienceMergeCandidates = prettyJson.encodeToString(
                    JsonElement.serializer(),
                    data
                )
            } catch (error: Exception) {
                experienceMergeError = error.message
            } finally {
                experienceMergeLoading = false
            }
        }
    }

    fun previewExperienceMerge() {
        val currentApi = api ?: return
        val ids = Regex("[A-Za-z0-9._:-]+")
            .findAll(experienceMergeIds)
            .map { it.value }
            .distinct()
            .toList()
        if (ids.size !in 2..6) {
            experienceMergeError = "请填写 2–6 个不同的经验 ID。"
            return
        }
        scope.launch {
            try {
                experienceMergeLoading = true
                experienceMergeError = null
                val data = currentApi.post(
                    "/api/experience/merge/preview",
                    buildJsonObject {
                        put("insight_ids", JsonArray(ids.map { JsonPrimitive(it) }))
                    }.toString()
                )
                experienceMergeToken = data.string("token")
                experienceMergeDraft = prettyJson.encodeToString(
                    JsonElement.serializer(),
                    data
                )
            } catch (error: Exception) {
                experienceMergeError = error.message
            } finally {
                experienceMergeLoading = false
            }
        }
    }

    fun confirmExperienceMerge() {
        val currentApi = api ?: return
        if (experienceMergeToken.isBlank()) {
            experienceMergeError = "请先生成并核对合并稿。"
            return
        }
        scope.launch {
            try {
                experienceMergeLoading = true
                experienceMergeError = null
                currentApi.post(
                    "/api/experience/merge",
                    buildJsonObject {
                        put("token", experienceMergeToken)
                        put("confirmed", true)
                    }.toString()
                )
                experienceMergeOpen = false
                experienceMergeToken = ""
                experienceMergeDraft = ""
                toast = "经验整理已保存，原件可撤销"
                resources.remove(Section.EXPERIENCE)
                loadSection(Section.EXPERIENCE)
            } catch (error: Exception) {
                experienceMergeError = error.message
            } finally {
                experienceMergeLoading = false
            }
        }
    }

    fun openProxyAction(operation: String, item: ResourceItem? = null) {
        val currentApi = api ?: return
        scope.launch {
            try {
                val root = currentApi.get("/api/proxies").objectOrEmpty()
                val version = root.long("version")
                val id = item?.id.orEmpty()
                val action = when (operation) {
                    "subscribe" -> JsonActionState(
                        title = "添加代理订阅",
                        description = "填写 HTTPS 订阅地址，后端会将其加密保存。",
                        initialJson = prettyJson.encodeToString(
                            JsonElement.serializer(),
                            buildJsonObject {
                                put("name", "")
                                put("url", "")
                                put("version", version)
                            }
                        ),
                        method = "POST",
                        pathTemplate = "/api/proxies/subscribe",
                        reloadSection = Section.PROXIES,
                        successMessage = "代理订阅已添加"
                    )
                    "import" -> JsonActionState(
                        title = "导入代理配置",
                        description = "粘贴 Clash/Mihomo 内联节点内容。",
                        initialJson = prettyJson.encodeToString(
                            JsonElement.serializer(),
                            buildJsonObject {
                                put("content", "")
                                put("version", version)
                            }
                        ),
                        method = "POST",
                        pathTemplate = "/api/proxies/import",
                        reloadSection = Section.PROXIES,
                        successMessage = "代理节点已导入"
                    )
                    "delete" -> JsonActionState(
                        title = "删除代理节点",
                        description = "确认删除选中的代理节点。",
                        initialJson = prettyJson.encodeToString(
                            JsonElement.serializer(),
                            buildJsonObject {
                                put("kind", "nodes")
                                put("id", id)
                                put("version", version)
                            }
                        ),
                        method = "POST",
                        pathTemplate = "/api/proxies/delete",
                        reloadSection = Section.PROXIES,
                        successMessage = "代理节点已删除"
                    )
                    "plan" -> JsonActionState(
                        title = "创建固定出口方案",
                        description = "按数组顺序填写节点 ID，形成固定链路。",
                        initialJson = prettyJson.encodeToString(
                            JsonElement.serializer(),
                            buildJsonObject {
                                put("name", "")
                                put("nodes", JsonArray(if (id.isBlank()) emptyList() else listOf(kotlinx.serialization.json.JsonPrimitive(id))))
                                put("version", version)
                            }
                        ),
                        method = "POST",
                        pathTemplate = "/api/proxies/plan",
                        reloadSection = Section.PROXIES,
                        successMessage = "固定出口方案已创建"
                    )
                    else -> JsonActionState(
                        title = "代理节点测速",
                        description = "选择 latency 或 download，nodes 为节点 ID 数组。",
                        initialJson = prettyJson.encodeToString(
                            JsonElement.serializer(),
                            buildJsonObject {
                                put("nodes", JsonArray(if (id.isBlank()) emptyList() else listOf(kotlinx.serialization.json.JsonPrimitive(id))))
                                put("mode", "latency")
                                put("version", version)
                            }
                        ),
                        method = "POST",
                        pathTemplate = "/api/proxies/benchmark",
                        reloadSection = Section.PROXIES,
                        successMessage = "测速任务已提交"
                    )
                }
                openJsonAction(action)
            } catch (error: Exception) {
                toast = error.message
            }
        }
    }

    fun toggleTheme() {
        darkTheme = !darkTheme
        desktopPreferences.putBoolean("dark_theme", darkTheme)
    }

    fun updateLanguage(value: String) {
        language = if (value == "en-US") "en-US" else "zh-CN"
        desktopPreferences.put("language", language)
        DesktopI18n.applyLanguage(language)
    }

    fun updateMotionPreference(value: String) {
        motionPreference = value.takeIf {
            it in setOf("system", "soft", "fast", "off")
        } ?: "system"
        desktopPreferences.put("motion_preference", motionPreference)
        DesktopI18n.applyMotionPreference(motionPreference)
    }

    fun updateNotificationsEnabled(enabled: Boolean) {
        notificationsEnabled = enabled
        desktopPreferences.putBoolean("notifications_enabled", enabled)
    }

    fun loadNotifications() {
        val currentApi = api ?: return
        scope.launch {
            try {
                notificationJson = currentApi.get("/api/notifications")
                val items = notificationJson?.objectOrEmpty()?.array("items").orEmpty()
                val readAt = desktopPreferences.getLong("notifications_read_at", 0L) / 1000.0
                notificationUnread = items.count { raw ->
                    val ts = raw.objectOrEmpty().element("ts")?.toString()?.toDoubleOrNull() ?: 0.0
                    ts > readAt
                }
                val notified = desktopPreferences.get("notified_notification_ids", "")
                    .split('|')
                    .filter(String::isNotBlank)
                    .toSet()
                val pending = items.map { it.objectOrEmpty() }
                    .filter { item ->
                        val ts = item.element("ts")?.toString()?.toDoubleOrNull() ?: 0.0
                        ts > readAt && item.string("id") !in notified
                    }
                    .take(3)
                if (notificationsEnabled && pending.isNotEmpty()) {
                    pending.forEach { item -> showTrayNotification(item) }
                    val ids = (notified.toList() + pending.map { it.string("id") })
                        .takeLast(120)
                        .toSet()
                    desktopPreferences.put("notified_notification_ids", ids.joinToString("|"))
                }
            } catch (error: Exception) {
                toast = "通知读取失败：${error.message}"
            }
        }
    }

    fun markNotificationsRead() {
        notificationUnread = 0
        desktopPreferences.putLong("notifications_read_at", System.currentTimeMillis())
    }

    private fun showTrayNotification(item: kotlinx.serialization.json.JsonObject) {
        if (!SystemTray.isSupported()) return
        runCatching {
            val tray = SystemTray.getSystemTray()
            val iconUrl = AppController::class.java.getResource("/composeResources/favicon.png")
                ?: AppController::class.java.getResource("/favicon.png")
            val image = iconUrl?.let { Toolkit.getDefaultToolkit().getImage(it) }
                ?: BufferedImage(16, 16, BufferedImage.TYPE_INT_ARGB).also { fallback ->
                    val graphics = fallback.createGraphics()
                    graphics.color = java.awt.Color(51, 156, 255)
                    graphics.fillOval(0, 0, 16, 16)
                    graphics.dispose()
                }
            val sessionId = item.string("session_id")
            val trayIcon = TrayIcon(image, "灵枢 · SpiritScout").apply {
                isImageAutoSize = true
                toolTip = item.string("title").ifBlank { "灵枢提醒" }
                addActionListener {
                    if (sessionId.isNotBlank()) openNotificationSession(sessionId)
                    tray.remove(this)
                }
            }
            val popup = PopupMenu()
            popup.add(MenuItem("打开灵枢").apply {
                addActionListener {
                    if (sessionId.isNotBlank()) openNotificationSession(sessionId)
                    tray.remove(trayIcon)
                }
            })
            trayIcon.popupMenu = popup
            tray.add(trayIcon)
            trayIcon.displayMessage(
                item.string("title").ifBlank { "灵枢提醒" },
                item.string("message").ifBlank { item.string("session_title") },
                TrayIcon.MessageType.INFO
            )
            scope.launch {
                kotlinx.coroutines.delay(12_000)
                runCatching { tray.remove(trayIcon) }
            }
        }
    }

    fun openNotificationSession(sessionId: String) {
        val currentApi = api ?: return
        if (sessionId.isBlank()) return
        scope.launch {
            try {
                openSession(
                    SessionItem.fromJson(
                        currentApi.get("/api/sessions/${url(sessionId)}")
                    )
                )
            } catch (error: Exception) {
                toast = error.message
            }
        }
    }

    fun chooseDashboardPeriod(period: String) {
        dashboardPeriod = period
        scope.launch { loadDashboardInternal() }
    }

    fun login(username: String, password: String) {
        val currentApi = api ?: return
        scope.launch {
            try {
                loginError = null
                if (!currentApi.login(username, password)) {
                    loginError = "用户名或密码不正确。"
                    return@launch
                }
                requiresLogin = false
                booting = true
                bootMessage = "正在加载工作区…"
                loadDashboardInternal()
                loadSessionsInternal()
                booting = false
            } catch (error: Exception) {
                loginError = error.message ?: "登录失败"
            }
        }
    }

    fun openDataDirectory() {
        val path = Path.of(System.getenv("LOCALAPPDATA") ?: System.getProperty("user.home"))
            .resolve("SpiritScout")
        Files.createDirectories(path)
        java.awt.Desktop.getDesktop().open(path.toFile())
    }

    fun openLogFile() {
        backend.logPath?.let {
            if (Files.exists(it)) java.awt.Desktop.getDesktop().open(it.toFile())
        }
    }

    fun checkUpdates() {
        val currentApi = api ?: return
        scope.launch {
            updateBusy = true
            updateError = null
            try {
                updateJson = currentApi.post("/api/updates/check", "{}")
                toast = "更新检查完成"
            } catch (error: Exception) {
                updateError = error.message ?: "更新检查失败"
            } finally {
                updateBusy = false
            }
        }
    }

    fun refreshUpdateStatus(details: Boolean = true) {
        val currentApi = api ?: return
        scope.launch {
            updateBusy = true
            updateError = null
            try {
                updateJson = currentApi.get("/api/updates?details=$details")
            } catch (error: Exception) {
                updateError = error.message
            } finally {
                updateBusy = false
            }
        }
    }

    fun applyUpdate(tag: String) {
        val currentApi = api ?: return
        if (tag.isBlank()) return
        scope.launch {
            updateBusy = true
            updateError = null
            try {
                updateJson = currentApi.post(
                    "/api/updates/apply",
                    buildJsonObject { put("tag", tag) }.toString()
                )
                toast = "更新已开始，服务将短暂重启"
            } catch (error: Exception) {
                updateError = error.message ?: "更新启动失败"
            } finally {
                updateBusy = false
            }
        }
    }

    fun loadStorageOverview() {
        val currentApi = api ?: return
        scope.launch {
            try {
                storageJson = currentApi.get("/api/storage/sessions")
            } catch (error: Exception) {
                toast = "存储读取失败：${error.message}"
            }
        }
    }

    fun loadStoragePreview(sessionId: String) {
        val currentApi = api ?: return
        if (sessionId.isBlank()) return
        scope.launch {
            try {
                storagePreviewJson = currentApi.get("/api/sessions/${url(sessionId)}/storage")
            } catch (error: Exception) {
                toast = "存储预览失败：${error.message}"
            }
        }
    }

    fun runStorageCleanup(sessionId: String, database: Boolean, caches: Boolean) {
        val currentApi = api ?: return
        if (sessionId.isBlank()) return
        scope.launch {
            try {
                val result = currentApi.post(
                    "/api/sessions/${url(sessionId)}/storage/cleanup",
                    buildJsonObject {
                        put("confirm", true)
                        put("database", database)
                        put("caches", caches)
                    }.toString()
                )
                storagePreviewJson = result
                toast = "存储清理已启动"
            } catch (error: Exception) {
                toast = "存储清理失败：${error.message}"
            }
        }
    }

    fun loadAssetProviders() {
        val currentApi = api ?: return
        scope.launch {
            assetProvidersLoading = true
            assetProvidersError = null
            try {
                val items = currentApi.get("/api/resources/assets/providers").array("providers")
                assetProviders.clear()
                assetProviders += items.map { raw ->
                    val item = raw.objectOrEmpty()
                    AssetProviderItem(
                        provider = item.string("provider"),
                        name = providerDisplayName(item.string("provider")),
                        category = item.string("category"),
                        enabled = item.boolean("enabled"),
                        keyConfigured = item.boolean("key_configured"),
                        keySource = item.string("key_source"),
                        storedCredentials = item.boolean("stored_credentials"),
                        version = item.long("version")
                    )
                }
            } catch (error: Exception) {
                assetProvidersError = error.message ?: "资产情报 Provider 读取失败"
            } finally {
                assetProvidersLoading = false
            }
        }
    }

    fun saveAssetProvider(
        provider: String,
        enabled: Boolean,
        version: Long,
        email: String = "",
        apiKey: String = "",
        cookie: String = ""
    ) {
        val currentApi = api ?: return
        scope.launch {
            assetProvidersLoading = true
            assetProvidersError = null
            try {
                val payload = buildJsonObject {
                    put("enabled", enabled)
                    put("expected_version", version)
                    if (email.isNotBlank()) put("email", email.trim())
                    if (apiKey.isNotBlank()) put("api_key_value", apiKey.trim())
                    if (cookie.isNotBlank()) put("cookie_value", cookie.trim())
                }
                val path = if (provider == "fofa") {
                    "/api/resources/assets/fofa"
                } else {
                    "/api/resources/assets/providers/${url(provider)}"
                }
                currentApi.put(path, payload.toString())
                toast = "Provider 配置已保存"
                loadAssetProviders()
            } catch (error: Exception) {
                assetProvidersError = error.message ?: "Provider 配置保存失败"
            } finally {
                assetProvidersLoading = false
            }
        }
    }

    fun clearAssetProviderCredentials(provider: String, version: Long) {
        val currentApi = api ?: return
        scope.launch {
            assetProvidersLoading = true
            assetProvidersError = null
            try {
                val payload = buildJsonObject {
                    put("enabled", false)
                    put("clear_credentials", true)
                    put("expected_version", version)
                }
                val path = if (provider == "fofa") {
                    "/api/resources/assets/fofa"
                } else {
                    "/api/resources/assets/providers/${url(provider)}"
                }
                currentApi.put(path, payload.toString())
                toast = "Provider 凭据已清除"
                loadAssetProviders()
            } catch (error: Exception) {
                assetProvidersError = error.message ?: "Provider 凭据清除失败"
            } finally {
                assetProvidersLoading = false
            }
        }
    }

    fun logout() {
        val currentApi = api ?: return
        scope.launch {
            runCatching { currentApi.post("/api/auth/logout", "{}") }
            requiresLogin = true
            booting = false
            loginError = null
        }
    }

    private fun providerDisplayName(provider: String): String = when (provider) {
        "fofa" -> "FOFA"
        "hunter" -> "Hunter"
        "quake" -> "Quake"
        "zoomeye" -> "ZoomEye"
        "aiqicha" -> "爱企查"
        "qichacha" -> "企查查"
        else -> provider
    }

    suspend fun shutdown() {
        backend.stop()
        scope.cancel()
    }

    private suspend fun loadSection(target: Section) {
        when (target) {
            Section.AGENTS -> agentCatalog.refresh()
            Section.MODELS -> modelProviders.open()
            Section.MCP -> mcp.refresh()
            Section.SKILLS -> skills.refresh()
            Section.LOCAL_TOOLS -> localTools.refresh()
            Section.PROJECTS -> projectCatalog.refresh()
            Section.ASSETS -> assetCollection.open()
            Section.INTELLIGENCE -> loadResourceInternal(target, "/api/resources/assets/providers", "providers") { item ->
                ResourceItem(
                    id = item.string("id").ifBlank { item.string("provider") },
                    title = item.string("name").ifBlank { item.string("label") },
                    subtitle = item.string("description").ifBlank { item.string("category") },
                    meta = item.string("credential_source").ifBlank {
                        if (item.boolean("configured")) "凭据已配置" else "凭据未配置"
                    },
                    status = if (item.boolean("enabled")) "enabled" else "disabled",
                    rawJson = pretty(item)
                )
            }
            Section.PROXIES -> proxyPool.refresh()
            Section.TRAFFIC -> traffic.loadCatalog()
            Section.SCHEDULES -> schedules.refresh()
            Section.EXPERIENCE -> loadPagedResourceInternal(target, "/api/experience", "items") { item ->
                ResourceItem(
                    id = item.string("insight_id").ifBlank { item.string("id") },
                    title = item.string("insight").ifBlank { "经验记录" },
                    subtitle = item.string("context"),
                    meta = item.array("tags").joinToString(" · ") { it.toString().trim('"') }
                        .ifBlank { item.string("source_model") },
                    status = item.string("quality_status").ifBlank { "待核验" },
                    rawJson = pretty(item)
                )
            }
            Section.BROWSER_ACCOUNTS -> browserAccounts.refresh()
            Section.SETTINGS -> loadSystemInternal()
            Section.DASHBOARD -> loadDashboardInternal()
            Section.TASKS -> loadSessionsInternal()
            Section.WORKSPACE -> refreshWorkspaceInternal()
        }
    }

    private suspend fun loadDashboardInternal() {
        val currentApi = api ?: return
        loading[Section.DASHBOARD] = true
        errors[Section.DASHBOARD] = null
        try {
            val dashboard = currentApi.get("/api/dashboard?period=${url(dashboardPeriod)}").objectOrEmpty()
            val sessionList = currentApi.get("/api/sessions").objectOrEmpty()
            val systemRoot = currentApi.get("/api/system/resources").objectOrEmpty()
            val summary = dashboard.element("summary")?.objectOrEmpty() ?: dashboard
            val cache = summary.element("cache")?.objectOrEmpty()
            val hitRate = cache?.double("hit_rate") ?: 0.0
            val systemRootData = systemRoot.element("system")?.objectOrEmpty()
            val app = systemRoot.element("application")?.objectOrEmpty()
            system = SystemResourceSnapshot(
                cpu = systemRootData?.double("cpu_percent") ?: 0.0,
                memory = systemRootData?.double("memory_percent") ?: 0.0,
                appCpu = app?.double("cpu_percent") ?: 0.0,
                appMemoryMb = (app?.double("memory_rss") ?: 0.0) / 1048576.0,
                processCount = app?.int("process_count") ?: 0
            )

            metrics.clear()
            metrics += MetricItem(
                "会话总数",
                dashboard.long("total_sessions").toString(),
                "${dashboard.long("running")} 个运行中"
            )
            metrics += MetricItem(
                "模型调用",
                summary.long("calls").toString(),
                "今日请求"
            )
            metrics += MetricItem(
                "Token",
                formatTokens(summary.long("tokens")),
                "输入 ${formatTokens(summary.long("input_tokens"))}"
            )
            metrics += MetricItem(
                "缓存命中",
                if (hitRate > 0) "${(hitRate * 100).toInt()}%" else "—",
                if (hitRate > 0) "已有实测采样" else "等待请求",
                if (hitRate > 0) MetricTone.SUCCESS else MetricTone.NORMAL
            )

            sessions.clear()
            sessionList.array("sessions").forEach { sessions += SessionItem.fromJson(it) }
        } catch (error: Exception) {
            errors[Section.DASHBOARD] = error.message
        } finally {
            loading[Section.DASHBOARD] = false
        }
    }

    private suspend fun loadSessionsInternal() {
        val currentApi = api ?: return
        loading[Section.TASKS] = true
        errors[Section.TASKS] = null
        try {
            val root = currentApi.get("/api/sessions").objectOrEmpty()
            sessions.clear()
            root.array("sessions").forEach { sessions += SessionItem.fromJson(it) }
        } catch (error: Exception) {
            errors[Section.TASKS] = error.message
        } finally {
            loading[Section.TASKS] = false
        }
    }

    private suspend fun loadModelsInternal() {
        val currentApi = api ?: return
        try {
            val root = currentApi.get("/api/models").objectOrEmpty()
            models.clear()
            models += "自动"
            root.array("models").forEach {
                val name = it.objectOrEmpty().string("model")
                if (name.isNotBlank()) models += name
            }
        } catch (_: Exception) {
            if (models.isEmpty()) models += "自动"
        }
    }

    private suspend fun loadResourceInternal(
        target: Section,
        endpoint: String,
        arrayName: String,
        mapper: (kotlinx.serialization.json.JsonElement) -> ResourceItem
    ) {
        val currentApi = api ?: return
        loading[target] = true
        errors[target] = null
        try {
            val response = currentApi.get(endpoint)
            val root = response.objectOrEmpty()
            val items = when (response) {
                is JsonArray -> response
                else -> when {
                    root.element(arrayName) != null -> root.array(arrayName)
                    else -> root.array("items")
                }
            }
            resources[target] = items.map(mapper)
        } catch (error: Exception) {
            errors[target] = error.message
            resources.putIfAbsent(target, emptyList())
        } finally {
            loading[target] = false
        }
    }

    private suspend fun loadPagedResourceInternal(
        target: Section,
        endpoint: String,
        arrayName: String,
        mapper: (JsonElement) -> ResourceItem
    ) {
        val currentApi = api ?: return
        loading[target] = true
        errors[target] = null
        try {
            val collected = mutableListOf<ResourceItem>()
            var offset = 0
            var hasMore: Boolean
            do {
                val separator = if ('?' in endpoint) '&' else '?'
                val response = currentApi.get("$endpoint${separator}limit=${ResourcePaging.PAGE_SIZE}&offset=$offset")
                val root = response.objectOrEmpty()
                val items = when {
                    root.element(arrayName) != null -> root.array(arrayName)
                    else -> root.array("items")
                }
                collected += items.map(mapper)
                hasMore = root.element("has_more")?.toString()?.toBooleanStrictOrNull()
                    ?: (items.size >= ResourcePaging.PAGE_SIZE)
                offset = ResourcePaging.nextOffset(offset, ResourcePaging.PAGE_SIZE, items.size, hasMore)
                    ?: break
            } while (offset < 10_000)
            resources[target] = collected
        } catch (error: Exception) {
            errors[target] = error.message
            resources.putIfAbsent(target, emptyList())
        } finally {
            loading[target] = false
        }
    }

    private suspend fun refreshWorkspaceInternal() {
        val currentApi = api ?: return
        val current = selectedSession ?: return
        workspaceLoading = true
        workspaceError = null
        try {
            val root = currentApi.get("/api/sessions/${current.id}/state").objectOrEmpty()
            val session = root.element("session")?.let { SessionItem.fromJson(it) } ?: current
            selectedSession = session

            val timeline = mutableListOf<TimelineItem>()
            root.array("user_opinions").forEach {
                val text = it.objectOrEmpty().string("text")
                if (text.isNotBlank()) timeline += TimelineItem("你", text, TimelineKind.USER)
            }
            root.array("master_replies").forEach {
                val obj = it.objectOrEmpty()
                val text = obj.string("text").ifBlank { obj.string("detail") }.ifBlank { obj.string("content") }
                if (text.isNotBlank()) timeline += TimelineItem("灵枢", text, TimelineKind.MASTER)
            }
            root.array("findings").forEach {
                val obj = it.objectOrEmpty()
                val text = obj.string("text").ifBlank { obj.string("title") }
                if (text.isNotBlank()) timeline += TimelineItem("发现", text, TimelineKind.FINDING)
            }
            if (timeline.isEmpty()) {
                timeline += TimelineItem("灵枢", "任务已建立，等待下一轮执行状态。", TimelineKind.SYSTEM)
            }

            val tasks = root.array("tasks").map { raw ->
                val obj = raw.objectOrEmpty()
                val routes = obj.array("routes")
                WorkTask(
                    id = obj.string("task_id"),
                    title = obj.string("title").ifBlank { obj.string("task_type") },
                    agent = obj.string("agent_type"),
                    status = obj.string("status"),
                    summary = obj.string("result_summary"),
                    routesDone = routes.count {
                        it.objectOrEmpty().string("status") == "done"
                    },
                    routesTotal = routes.size
                )
            }
            loadSideAgentsInternal(currentApi, session, tasks)

            val vulns = root.element("vulns")?.objectOrEmpty()?.long("total") ?: 0
            val flags = root.element("flags")?.objectOrEmpty()?.long("total") ?: 0
            val layers = root.element("layers")?.objectOrEmpty()?.mapValues { (_, value) ->
                value.toString().toLongOrNull() ?: 0
            } ?: emptyMap()
            val approvals = root.array("pending_approvals").map { raw ->
                val obj = raw.objectOrEmpty()
                PendingApprovalItem(
                    id = obj.string("approval_id").ifBlank { obj.string("id") },
                    action = obj.string("action"),
                    purpose = obj.string("purpose").ifBlank { obj.string("detail") },
                    detail = obj.string("detail")
                )
            }
            val questions = root.array("pending_questions").map { raw ->
                val obj = raw.objectOrEmpty()
                PendingQuestionItem(
                    id = obj.string("question_id").ifBlank { obj.string("id") },
                    agent = obj.string("agent"),
                    question = obj.string("question"),
                    options = obj.array("options").map { it.toString().trim('"') },
                    multiple = obj.boolean("multiple"),
                    secret = obj.boolean("secret"),
                    rawJson = pretty(raw)
                )
            }

            workspace = WorkspaceSnapshot(
                session = session,
                timeline = timeline.takeLast(60),
                tasks = tasks,
                findings = root.array("findings").size,
                vulnerabilities = vulns.toInt(),
                flags = flags.toInt(),
                pendingApprovals = approvals,
                pendingQuestions = questions,
                layers = layers,
                rawJson = pretty(root)
            )
            if (workspaceTab != WorkspaceTab.CHAT) {
                loadWorkspaceTabInternal(workspaceTab)
            }
        } catch (error: Exception) {
            workspaceError = error.message
        } finally {
            workspaceLoading = false
        }
    }

    private fun startWorkspaceEventStream(sessionId: String) {
        stopWorkspaceEventStream()
        val currentApi = api ?: return
        workspaceEventOffset = 0L
        workspaceEventJob = scope.launch(Dispatchers.IO) {
            var retry = 0
            while (isActive) {
                val current = selectedSession ?: break
                if (current.id != sessionId) break
                try {
                    var streamDone = false
                    val stream = currentApi.openEventStream(
                        "/api/sessions/${url(sessionId)}/events?cursor=bytes&offset=$workspaceEventOffset"
                    )
                    stream.bufferedReader(StandardCharsets.UTF_8).use { reader ->
                        var eventType = "message"
                        var eventId = ""
                        val data = StringBuilder()
                        while (isActive) {
                            val line = reader.readLine() ?: break
                            when {
                                line.isBlank() -> {
                                    if (data.isNotEmpty()) {
                                        if (eventId.isNotBlank()) {
                                            workspaceEventOffset = eventId.toLongOrNull()
                                                ?: workspaceEventOffset
                                        }
                                        if (eventType == "audit") {
                                            handleWorkspaceAuditEvent(data.toString(), sessionId)
                                        }
                                        if (eventType == "done") streamDone = true
                                    }
                                    eventType = "message"
                                    eventId = ""
                                    data.clear()
                                    if (streamDone) break
                                }
                                line.startsWith("event:") -> eventType = line.substringAfter(':').trim()
                                line.startsWith("id:") -> eventId = line.substringAfter(':').trim()
                                line.startsWith("data:") -> {
                                    if (data.isNotEmpty()) data.append('\n')
                                    data.append(line.substringAfter(':').trimStart())
                                }
                            }
                        }
                    }
                    retry = 0
                    if (streamDone || doneForEventStream(sessionId)) break
                } catch (_: Exception) {
                    if (!isActive || selectedSession?.id != sessionId) break
                    retry += 1
                    delay((retry.coerceAtMost(5) * 1500).toLong())
                }
            }
        }
    }

    private fun doneForEventStream(sessionId: String): Boolean {
        val session = selectedSession ?: return true
        return session.id != sessionId || session.status in setOf(
            "completed", "stopped", "failed", "interrupted"
        )
    }

    private fun stopWorkspaceEventStream() {
        workspaceEventJob?.cancel()
        workspaceEventJob = null
    }

    private suspend fun handleWorkspaceAuditEvent(data: String, sessionId: String) {
        val event = runCatching { Json.parseToJsonElement(data).objectOrEmpty() }.getOrNull() ?: return
        val type = event.string("type")
        val detail = event.element("detail")?.objectOrEmpty() ?: JsonObject(emptyMap())
        val body = listOf(
            "content", "text", "message", "result", "result_summary",
            "summary", "command", "error", "detail"
        ).firstNotNullOfOrNull { key ->
            val value = detail.string(key).ifBlank { event.string(key) }
            value.takeIf(String::isNotBlank)
        }.orEmpty()
        if (body.isBlank() && type.isBlank()) return
        val kind = when {
            type.startsWith("user.") -> TimelineKind.USER
            type.startsWith("agent.") || type.startsWith("task.") -> TimelineKind.AGENT
            type.startsWith("vuln.") || type.startsWith("flag.") -> TimelineKind.FINDING
            type.startsWith("master.") -> TimelineKind.MASTER
            else -> TimelineKind.SYSTEM
        }
        val title = when {
            type.startsWith("user.") -> "你"
            type.startsWith("master.") -> "灵枢"
            type.startsWith("agent.") -> "子 Agent"
            type.startsWith("vuln.") -> "漏洞"
            type.startsWith("flag.") -> "Flag"
            type.startsWith("task.") -> "任务"
            type.isBlank() -> "轨迹"
            else -> type.substringBefore('.').replaceFirstChar { it.uppercase() }
        }
        withContext(Dispatchers.Swing) {
            if (selectedSession?.id != sessionId) return@withContext
            val current = workspace ?: return@withContext
            val next = TimelineItem(
                title = title,
                body = body.ifBlank { type },
                kind = kind
            )
            workspace = current.copy(timeline = (current.timeline + next).takeLast(200))
        }
        if (type.startsWith("task.") || type.startsWith("agent.") ||
            type.startsWith("vuln.") || type.startsWith("flag.") ||
            type.startsWith("system.")
        ) {
            scope.launch { refreshWorkspaceInternal() }
        }
    }

    private suspend fun loadWorkspaceTabInternal(tab: WorkspaceTab) {
        val currentApi = api ?: return
        val current = selectedSession ?: return
        workspaceTabLoading = true
        workspaceTabError = null
        try {
            val sid = current.id
            workspaceTabJson = when (tab) {
                WorkspaceTab.CHAT -> null
                WorkspaceTab.FILES,
                WorkspaceTab.DELIVERABLES -> currentApi.get("/api/sessions/$sid/deliverables?limit=100")
                WorkspaceTab.TOPOLOGY,
                WorkspaceTab.ASSETS,
                WorkspaceTab.OPPORTUNITIES,
                WorkspaceTab.CHALLENGES,
                WorkspaceTab.FLAGS,
                WorkspaceTab.RECORDS -> currentApi.get("/api/sessions/$sid/state")
                WorkspaceTab.VULNERABILITIES -> currentApi.get("/api/sessions/$sid/vulnerabilities?limit=100")
                WorkspaceTab.EXPERIENCE -> currentApi.get("/api/sessions/$sid/experience")
                WorkspaceTab.TRAFFIC -> {
                    traffic.refresh(sid)
                    JsonObject(emptyMap())
                }
                WorkspaceTab.BACKGROUND -> currentApi.get("/api/sessions/$sid/background-tasks")
                WorkspaceTab.EVENTS -> currentApi.get("/api/sessions/$sid/audit-page?activity=true&limit=250")
                WorkspaceTab.REPORT -> currentApi.get("/api/sessions/$sid/report")
            }
        } catch (error: Exception) {
            workspaceTabError = error.message
        } finally {
            workspaceTabLoading = false
        }
    }

    private suspend fun loadSideAgentsInternal(
        currentApi: SpiritApi,
        session: SessionItem,
        tasks: List<WorkTask>
    ) {
        val mode = session.mode.lowercase()
        if (session.isSideSession || mode !in setOf("src", "ctf")) {
            sideAgents.clear()
            return
        }
        val rosterKey = "${session.id}:$mode"
        if (sideRosterLoadedFor != rosterKey || sideRosterCache.isEmpty()) {
            val roster = currentApi.get("/api/agents").array("roster")
            sideRosterCache = roster.mapNotNull { raw ->
                val item = raw.objectOrEmpty()
                val actor = item.string("key")
                if (actor.isBlank() || actor in setOf("master", "secretary", "report")) {
                    null
                } else {
                    SideAgentOption(
                        actor = actor,
                        label = item.string("name").ifBlank { actor },
                        status = item.string("status"),
                        modes = item.array("modes").map { it.toString().trim('"').lowercase() }.toSet()
                    )
                }
            }
            sideRosterLoadedFor = rosterKey
        }
        val merged = linkedMapOf<String, SideAgentOption>()
        sideRosterCache
            .filter { it.status.isBlank() || it.status == "available" }
            .filter { it.modes.isEmpty() || mode in it.modes }
            .forEach { merged[it.actor] = it }
        tasks.map { it.agent }.filter(String::isNotBlank).distinct().forEach { actor ->
            merged.putIfAbsent(
                actor,
                SideAgentOption(
                    actor = actor,
                    label = sideRosterCache.firstOrNull { it.actor == actor }?.label ?: actor,
                    status = tasks.firstOrNull { it.agent == actor }?.status.orEmpty(),
                    modes = setOf(mode)
                )
            )
        }
        sideAgents.clear()
        sideAgents += merged.values
        if (sideActor.isNotBlank() && sideAgents.none { it.actor == sideActor }) {
            selectSideAgent("")
        }
    }

    private suspend fun loadSystemInternal() {
        val currentApi = api ?: return
        loading[Section.SETTINGS] = true
        errors[Section.SETTINGS] = null
        try {
            val root = currentApi.get("/api/system/resources").objectOrEmpty()
            val systemData = root.element("system")?.objectOrEmpty()
            val app = root.element("application")?.objectOrEmpty()
            system = SystemResourceSnapshot(
                cpu = systemData?.double("cpu_percent") ?: 0.0,
                memory = systemData?.double("memory_percent") ?: 0.0,
                appCpu = app?.double("cpu_percent") ?: 0.0,
                appMemoryMb = (app?.double("memory_rss") ?: 0.0) / 1048576.0,
                processCount = app?.int("process_count") ?: 0
            )
        } catch (error: Exception) {
            errors[Section.SETTINGS] = error.message
        } finally {
            loading[Section.SETTINGS] = false
        }
    }

    private fun pretty(element: JsonElement): String =
        prettyJson.encodeToString(JsonElement.serializer(), element)

    private fun versionOf(item: ResourceItem?): Long =
        item?.let { runCatching { Json.parseToJsonElement(it.rawJson).jsonObject["version"]?.toString()?.toLong() }.getOrNull() }
            ?: 0L

    private suspend fun buildSkillAction(
        currentApi: SpiritApi,
        item: ResourceItem?,
        operation: String
    ): JsonActionState? {
        if (operation == "new") {
            return JsonActionState(
                title = "新建 Skill",
                description = "填写唯一标识和 Skill JSON；正文支持 Markdown。",
                initialJson = prettyJson.encodeToString(
                    JsonElement.serializer(),
                    Json.parseToJsonElement(
                        """{"data":{"skill_id":"my-skill","domain":"custom","description":"","body":"# 新 Skill\n\n适用条件：","enabled":true,"tier":"domain","aliases":[],"tags":[]},"expected_version":0}"""
                    )
                ),
                method = "PUT",
                pathTemplate = "/api/resources/skills/{id}",
                requiresId = true,
                reloadSection = Section.SKILLS,
                successMessage = "Skill 已保存"
            )
        }
        val current = item ?: return null
        val detail = currentApi.get("/api/resources/skills/${url(current.id)}")
        if (operation == "edit") {
            val body = buildJsonObject {
                put("data", detail)
                put("expected_version", detail.objectOrEmpty().long("version"))
            }
            return JsonActionState(
                title = "编辑 Skill · ${current.title}",
                description = "保存会创建新版本；正文和文件内容都会保留。",
                initialId = current.id,
                initialJson = pretty(body),
                method = "PUT",
                pathTemplate = "/api/resources/skills/{id}",
                reloadSection = Section.SKILLS,
                successMessage = "Skill 已更新"
            )
        }
        return JsonActionState(
            title = "删除 Skill · ${current.title}",
            description = "确认删除后，该 Skill 将从目录中移除。",
            initialId = current.id,
            method = "DELETE",
            pathTemplate = "/api/resources/skills/{id}?expected_version=${detail.objectOrEmpty().long("version")}",
            reloadSection = Section.SKILLS,
            successMessage = "Skill 已删除"
        )
    }

    private fun buildMcpAction(item: ResourceItem?, operation: String): JsonActionState? {
        if (operation == "new") {
            return JsonActionState(
                title = "新建 MCP",
                description = "填写唯一名称以及 stdio/http/sse 连接配置。",
                initialJson = prettyJson.encodeToString(
                    JsonElement.serializer(),
                    Json.parseToJsonElement(
                        """{"data":{"name":"my-mcp","transport":"stdio","command":"","args":[],"url":"","timeout":180.0,"default_risk":"readonly","risk_by_action":true,"tool_risk_overrides":{},"internet_search":false,"scope_enforcement":"required","target_params":[],"allowed_agents":[],"enabled":false,"headers":{},"env":{}},"expected_version":0}"""
                    )
                ),
                method = "PUT",
                pathTemplate = "/api/resources/mcp/{id}",
                requiresId = true,
                reloadSection = Section.MCP,
                successMessage = "MCP 已保存"
            )
        }
        val current = item ?: return null
        val root = runCatching { Json.parseToJsonElement(current.rawJson).jsonObject }.getOrNull() ?: return null
        val data = root["data"] ?: return null
        val version = root["version"]?.toString()?.toLongOrNull() ?: 0L
        if (operation == "edit") {
            val body = buildJsonObject {
                put("data", data)
                put("expected_version", version)
            }
            return JsonActionState(
                title = "编辑 MCP · ${current.title}",
                description = "修改连接方式、命令、参数、权限和启用状态。",
                initialId = current.id,
                initialJson = pretty(body),
                method = "PUT",
                pathTemplate = "/api/resources/mcp/{id}",
                reloadSection = Section.MCP,
                successMessage = "MCP 已更新"
            )
        }
        return JsonActionState(
            title = "删除 MCP · ${current.title}",
            description = "确认删除该 MCP 接入配置。",
            initialId = current.id,
            method = "DELETE",
            pathTemplate = "/api/resources/mcp/{id}?expected_version=$version",
            reloadSection = Section.MCP,
            successMessage = "MCP 已删除"
        )
    }

    private fun buildAgentAction(item: ResourceItem?, operation: String): JsonActionState? {
        val current = item ?: return null
        if (operation != "edit") return null
        return JsonActionState(
            title = "绑定模型 · ${current.title}",
            description = "填写模型 ID；留空表示使用系统默认模型。",
            initialId = current.id,
            initialJson = """{"model":""}""",
            method = "PUT",
            pathTemplate = "/api/agents/{id}",
            reloadSection = Section.AGENTS,
            successMessage = "编队模型已更新"
        )
    }

    private fun buildModelAction(item: ResourceItem?, operation: String): JsonActionState? {
        if (operation == "new") {
            return JsonActionState(
                title = "添加模型",
                description = "填写模型 ID、供应商引用和能力。",
                initialJson = """{"model":"","provider_ref":"","context_window":0,"max_output_tokens":0,"capabilities":[],"reasoning_effort_levels":[],"prompt_caching":"provider_default"}""",
                method = "POST",
                pathTemplate = "/api/models",
                reloadSection = Section.MODELS,
                successMessage = "模型已保存"
            )
        }
        val current = item ?: return null
        return if (operation == "edit") {
            JsonActionState(
                title = "编辑模型 · ${current.title}",
                description = "修改能力、上下文窗口和缓存策略。",
                initialId = current.id,
                initialJson = current.rawJson,
                method = "PUT",
                pathTemplate = "/api/models/{id}",
                reloadSection = Section.MODELS,
                successMessage = "模型已更新"
            )
        } else {
            JsonActionState(
                title = "删除模型 · ${current.title}",
                description = "确认从模型注册表删除该模型。",
                initialId = current.id,
                method = "DELETE",
                pathTemplate = "/api/models/{id}",
                reloadSection = Section.MODELS,
                successMessage = "模型已删除"
            )
        }
    }

    private fun buildProjectAction(item: ResourceItem?, operation: String): JsonActionState? {
        if (operation == "new") {
            return JsonActionState(
                title = "新建项目",
                description = "项目用于关联资产、会话、漏洞和报告。",
                initialJson = """{"name":"新项目","description":""}""",
                method = "POST",
                pathTemplate = "/api/projects",
                reloadSection = Section.PROJECTS,
                successMessage = "项目已创建"
            )
        }
        val current = item ?: return null
        return if (operation == "edit") {
            JsonActionState(
                title = "编辑项目 · ${current.title}",
                description = "修改项目名称和说明。",
                initialId = current.id,
                initialJson = current.rawJson,
                method = "PUT",
                pathTemplate = "/api/projects/{id}",
                reloadSection = Section.PROJECTS,
                successMessage = "项目已更新"
            )
        } else {
            JsonActionState(
                title = "删除项目 · ${current.title}",
                description = "项目内的资产和记录会按后端规则处理，请确认后删除。",
                initialId = current.id,
                method = "DELETE",
                pathTemplate = "/api/projects/{id}?confirm=true",
                reloadSection = Section.PROJECTS,
                successMessage = "项目已删除"
            )
        }
    }

    private fun buildScheduleAction(item: ResourceItem?, operation: String): JsonActionState? {
        if (operation == "new") {
            val runAt = Instant.now().plusSeconds(3600).toString()
            return JsonActionState(
                title = "新建自动任务",
                description = "填写任务内容、执行时间和周期。",
                initialJson = prettyJson.encodeToString(
                    JsonElement.serializer(),
                    Json.parseToJsonElement(
                        """{"name":"自动任务","message":"","mode":"src","target":"","scope":[],"model":"","project_id":"","run_at":"$runAt","interval_seconds":null}"""
                    )
                ),
                method = "POST",
                pathTemplate = "/api/schedules",
                reloadSection = Section.SCHEDULES,
                successMessage = "自动任务已创建"
            )
        }
        val current = item ?: return null
        return if (operation == "edit") {
            JsonActionState(
                title = "编辑自动任务 · ${current.title}",
                description = "修改后请保存；可直接在 JSON 中调整 run_at 和周期。",
                initialId = current.id,
                initialJson = current.rawJson,
                method = "PUT",
                pathTemplate = "/api/schedules/{id}",
                reloadSection = Section.SCHEDULES,
                successMessage = "自动任务已更新"
            )
        } else {
            JsonActionState(
                title = "删除自动任务 · ${current.title}",
                description = "确认删除该计划任务。",
                initialId = current.id,
                method = "DELETE",
                pathTemplate = "/api/schedules/{id}",
                reloadSection = Section.SCHEDULES,
                successMessage = "自动任务已删除"
            )
        }
    }

    private fun buildBrowserAccountAction(item: ResourceItem?, operation: String): JsonActionState? {
        if (operation == "new") {
            val id = "account-" + System.currentTimeMillis().toString(36)
            return JsonActionState(
                title = "新建浏览器账号",
                description = "配置来源域名、MFA 方式、保留策略和可选登录态。",
                initialId = id,
                initialJson = prettyJson.encodeToString(
                    JsonElement.serializer(),
                    Json.parseToJsonElement(
                        """{"data":{"name":"新账号","role":"","origins":[],"retain":true,"ttl_days":30,"mfa_method":"none","clear_credentials":false},"expected_version":0}"""
                    )
                ),
                method = "PUT",
                pathTemplate = "/api/browser-accounts/{id}",
                requiresId = true,
                reloadSection = Section.BROWSER_ACCOUNTS,
                successMessage = "浏览器账号已保存"
            )
        }
        val current = item ?: return null
        val root = runCatching { Json.parseToJsonElement(current.rawJson).jsonObject }.getOrNull() ?: return null
        val version = root["version"]?.toString()?.toLongOrNull() ?: 0L
        if (operation == "edit") {
            val data = buildJsonObject {
                root.forEach { (key, value) ->
                    if (key !in setOf("id", "version", "created_at", "updated_at", "status")) {
                        put(key, value)
                    }
                }
            }
            val body = buildJsonObject {
                put("data", data)
                put("expected_version", version)
            }
            return JsonActionState(
                title = "编辑浏览器账号 · ${current.title}",
                description = "留空的敏感字段会保持原值。",
                initialId = current.id,
                initialJson = pretty(body),
                method = "PUT",
                pathTemplate = "/api/browser-accounts/{id}",
                reloadSection = Section.BROWSER_ACCOUNTS,
                successMessage = "浏览器账号已更新"
            )
        }
        return JsonActionState(
            title = "删除浏览器账号 · ${current.title}",
            description = "将删除账号及已保存的登录态和凭据。",
            initialId = current.id,
            method = "DELETE",
            pathTemplate = "/api/browser-accounts/{id}?expected_version=$version",
            reloadSection = Section.BROWSER_ACCOUNTS,
            successMessage = "浏览器账号已删除"
        )
    }

    private fun buildExperienceAction(item: ResourceItem?, operation: String): JsonActionState? {
        val current = item ?: return null
        if (operation != "delete") return null
        return JsonActionState(
            title = "删除经验 · ${current.title}",
            description = "确认删除该条经验记录。",
            initialId = current.id,
            method = "DELETE",
            pathTemplate = "/api/experience/{id}",
            reloadSection = Section.EXPERIENCE,
            successMessage = "经验已删除"
        )
    }

    private suspend fun buildLocalToolsAction(currentApi: SpiritApi): JsonActionState {
        val root = currentApi.get("/api/local-tools").objectOrEmpty()
        val config = root.element("config") ?: JsonObject(emptyMap())
        return JsonActionState(
            title = "本地工具配置",
            description = "配置启用状态、目录、超时和扫描上限。",
            initialJson = pretty(config),
            method = "PUT",
            pathTemplate = "/api/local-tools",
            reloadSection = Section.LOCAL_TOOLS,
            successMessage = "本地工具配置已保存"
        )
    }

    private fun url(value: String): String =
        URLEncoder.encode(value, StandardCharsets.UTF_8)

    private companion object {
        val prettyJson = Json { prettyPrint = true }
    }

    private fun formatTokens(value: Long): String = when {
        value >= 1_000_000 -> "%.2fM".format(value / 1_000_000.0)
        value >= 1_000 -> "%.1fK".format(value / 1_000.0)
        else -> value.toString()
    }
}
