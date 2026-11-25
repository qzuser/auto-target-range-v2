package com.spiritscout.desktop.state

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.spiritscout.desktop.model.PendingApprovalItem
import com.spiritscout.desktop.model.TaskOption
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
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.swing.Swing
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.net.URLEncoder
import java.nio.charset.StandardCharsets

data class AssetCampaignRow(
    val id: String,
    val projectId: String,
    val status: String,
    val targets: List<String>,
    val model: String,
    val proxyPlanId: String,
    val proxyName: String,
    val commands: Int,
    val candidates: Int,
    val assetsRevision: Long,
    val error: String,
    val approvals: List<PendingApprovalItem>,
    val createdAt: Double,
    val startedAt: Double,
    val finishedAt: Double,
    val rawJson: String
)

data class AssetTargetRow(
    val value: String,
    val title: String,
    val assetType: String,
    val ip: String,
    val cname: String,
    val source: String,
    val collectionMethod: String,
    val verificationStatus: String,
    val httpStatus: String,
    val httpError: String,
    val egressName: String,
    val exitIp: String,
    val observations: List<String>
)

data class AssetOutputLine(
    val seq: Int,
    val level: String,
    val message: String,
    val createdAt: Double
)

class AssetCollectionController(
    private val apiProvider: () -> SpiritApi?,
    private val scope: CoroutineScope
) {
    private val prettyJson = Json { prettyPrint = true }
    private var optionsLoaded = false
    private var eventJob: Job? = null

    val projects = mutableStateListOf<TaskOption>()
    val models = mutableStateListOf<TaskOption>()
    val proxyPlans = mutableStateListOf<TaskOption>()
    val campaigns = mutableStateListOf<AssetCampaignRow>()
    val targets = mutableStateListOf<AssetTargetRow>()
    val outputs = mutableStateListOf<AssetOutputLine>()

    var selectedProjectId by mutableStateOf("")
        private set
    var selectedModel by mutableStateOf("")
        private set
    var selectedProxyPlanId by mutableStateOf("direct")
        private set
    var selectedCampaignId by mutableStateOf("")
        private set
    var excludedAssets by mutableStateOf<List<String>>(emptyList())
        private set
    var loading by mutableStateOf(false)
        private set
    var detailLoading by mutableStateOf(false)
        private set
    var actionBusy by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set
    var connectionStatus by mutableStateOf("")
        private set

    fun reset() {
        eventJob?.cancel()
        eventJob = null
        optionsLoaded = false
        projects.clear()
        models.clear()
        proxyPlans.clear()
        campaigns.clear()
        targets.clear()
        outputs.clear()
        selectedProjectId = ""
        selectedModel = ""
        selectedProxyPlanId = "direct"
        selectedCampaignId = ""
        excludedAssets = emptyList()
        loading = false
        detailLoading = false
        actionBusy = false
        error = null
        connectionStatus = ""
    }

    fun open() {
        val currentApi = apiProvider() ?: return
        scope.launch {
            loading = true
            error = null
            try {
                if (!optionsLoaded) {
                    val (projectRoot, modelRoot, proxyRoot) = coroutineScope {
                        val projectsRequest = async { currentApi.get("/api/projects") }
                        val modelsRequest = async { currentApi.get("/api/models") }
                        val proxiesRequest = async { currentApi.get("/api/proxies") }
                        Triple(projectsRequest.await(), modelsRequest.await(), proxiesRequest.await())
                    }
                    projects.clear()
                    projects += projectRoot.array("projects")
                        .map { it.objectOrEmpty() }
                        .filter { it.string("project_id").isNotBlank() && !it.boolean("read_only") }
                        .map {
                            TaskOption(
                                id = it.string("project_id"),
                                label = it.string("name").ifBlank { it.string("project_id") },
                                detail = it.string("description")
                            )
                        }
                    models.clear()
                    models += modelRoot.array("models").mapNotNull { raw ->
                        val item = raw.objectOrEmpty()
                        val key = item.string("key").ifBlank { item.string("model") }
                        if (key.isBlank()) null else TaskOption(
                            id = key,
                            label = listOf(item.string("provider_ref"), item.string("model"))
                                .filter(String::isNotBlank)
                                .joinToString(" / ")
                                .ifBlank { key }
                        )
                    }
                    proxyPlans.clear()
                    proxyPlans += proxyRoot.array("plans").mapNotNull { raw ->
                        val item = raw.objectOrEmpty()
                        val id = item.string("id")
                        if (id.isBlank()) null else TaskOption(
                            id = id,
                            label = item.string("name").ifBlank { id }
                        )
                    }
                    optionsLoaded = true
                    if (projects.none { it.id == selectedProjectId }) {
                        selectedProjectId = projects.firstOrNull()?.id.orEmpty()
                    }
                    if (models.none { it.id == selectedModel }) selectedModel = ""
                    if (proxyPlans.none { it.id == selectedProxyPlanId }) selectedProxyPlanId = "direct"
                }
                refreshCampaigns(currentApi)
            } catch (failure: Exception) {
                error = failure.message ?: "资产收集读取失败"
            } finally {
                loading = false
            }
        }
    }

    fun selectProject(projectId: String) {
        selectedProjectId = projectId
        selectedCampaignId = ""
        campaigns.clear()
        targets.clear()
        outputs.clear()
        eventJob?.cancel()
        open()
    }

    fun selectModel(model: String) {
        selectedModel = model
    }

    fun selectProxyPlan(planId: String) {
        selectedProxyPlanId = planId
    }

    fun refresh() {
        open()
    }

    fun selectCampaign(campaignId: String) {
        if (selectedCampaignId == campaignId) return
        selectedCampaignId = campaignId
        targets.clear()
        outputs.clear()
        loadDetails()
        connectEvents()
    }

    fun loadDetails() {
        val currentApi = apiProvider() ?: return
        val campaignId = selectedCampaignId
        if (campaignId.isBlank()) return
        scope.launch {
            detailLoading = true
            try {
                val root = currentApi.get("/api/asset-campaigns/${enc(campaignId)}/targets")
                if (selectedCampaignId != campaignId) return@launch
                excludedAssets = root.array("excluded_assets").map { it.toString().trim('"') }
                targets.clear()
                targets += root.array("targets").map { raw ->
                    val item = raw.objectOrEmpty()
                    AssetTargetRow(
                        value = item.string("value"),
                        title = item.string("title"),
                        assetType = item.string("asset_type"),
                        ip = item.string("ip"),
                        cname = item.string("cname"),
                        source = item.string("source"),
                        collectionMethod = item.string("collection_method"),
                        verificationStatus = item.string("verification_status"),
                        httpStatus = item.string("http_status"),
                        httpError = item.string("http_error"),
                        egressName = item.string("egress_name"),
                        exitIp = item.string("exit_ip"),
                        observations = item.array("http_observations").map { observation ->
                            val row = observation.objectOrEmpty()
                            listOf(
                                row.string("egress_name").ifBlank { "出口未知" },
                                row.string("exit_ip"),
                                row.string("http_status").takeIf(String::isNotBlank)?.let { "HTTP $it" }.orEmpty(),
                                row.string("http_error")
                            ).filter(String::isNotBlank).joinToString(" · ")
                        }
                    )
                }
            } catch (failure: Exception) {
                error = failure.message ?: "资产结果读取失败"
            } finally {
                detailLoading = false
            }
        }
    }

    fun createCampaign(
        targetsText: String,
        excludedText: String,
        instruction: String,
        directFallback: Boolean,
        oneforallPath: String = "",
        pythonPath: String = "",
        timeoutText: String = "",
        brute: Boolean = false
    ) {
        val currentApi = apiProvider() ?: return
        val projectId = selectedProjectId
        val model = selectedModel
        val proxy = selectedProxyPlanId
        if (projectId.isBlank() || model.isBlank()) {
            error = "请选择项目和资产收集模型。"
            return
        }
        val targetValues = splitLines(targetsText)
        if (targetValues.isEmpty()) {
            error = "至少填写一个目标资产或组织主体。"
            return
        }
        scope.launch {
            actionBusy = true
            error = null
            try {
                val payload = buildJsonObject {
                    put("model", model)
                    put("proxy_plan_id", proxy)
                    put("direct_fallback", directFallback)
                    put("targets", JsonList(targetValues))
                    put("excluded_assets", JsonList(splitLines(excludedText)))
                    put("instruction", instruction.trim())
                    put("oneforall_path", oneforallPath.trim())
                    put("python", pythonPath.trim())
                    put("timeout_seconds", timeoutText.toIntOrNull()?.coerceIn(30, 7200) ?: 600)
                    put("brute", brute)
                }
                val created = currentApi.post(
                    "/api/projects/${enc(projectId)}/asset-campaigns",
                    payload.toString()
                ).objectOrEmpty()
                val id = created.string("campaign_id")
                if (id.isNotBlank()) {
                    currentApi.post("/api/asset-campaigns/${enc(id)}/start")
                    selectedCampaignId = id
                    open()
                    selectCampaign(id)
                }
            } catch (failure: Exception) {
                error = failure.message ?: "资产收集任务创建失败"
            } finally {
                actionBusy = false
            }
        }
    }

    fun campaignAction(campaignId: String, operation: String) {
        val currentApi = apiProvider() ?: return
        if (campaignId.isBlank()) return
        scope.launch {
            actionBusy = true
            error = null
            try {
                val body = if (operation in setOf("start", "resume") && selectedModel.isNotBlank()) {
                    buildJsonObject { put("model", selectedModel) }.toString()
                } else {
                    null
                }
                if (body == null) {
                    currentApi.post("/api/asset-campaigns/${enc(campaignId)}/$operation")
                } else {
                    currentApi.post("/api/asset-campaigns/${enc(campaignId)}/$operation", body)
                }
                open()
                if (selectedCampaignId == campaignId) loadDetails()
            } catch (failure: Exception) {
                error = failure.message ?: "资产收集任务操作失败"
            } finally {
                actionBusy = false
            }
        }
    }

    fun deleteCampaign(campaignId: String) {
        val currentApi = apiProvider() ?: return
        scope.launch {
            actionBusy = true
            error = null
            try {
                currentApi.delete("/api/asset-campaigns/${enc(campaignId)}")
                if (selectedCampaignId == campaignId) {
                    selectedCampaignId = ""
                    targets.clear()
                    outputs.clear()
                    eventJob?.cancel()
                }
                open()
            } catch (failure: Exception) {
                error = failure.message ?: "资产收集任务删除失败"
            } finally {
                actionBusy = false
            }
        }
    }

    fun decideApproval(approvalId: String, allow: Boolean) {
        val currentApi = apiProvider() ?: return
        val campaignId = selectedCampaignId
        if (campaignId.isBlank()) return
        scope.launch {
            try {
                currentApi.post(
                    "/api/asset-campaigns/${enc(campaignId)}/approvals/${enc(approvalId)}",
                    buildJsonObject { put("allow", allow) }.toString()
                )
                loadDetails()
            } catch (failure: Exception) {
                error = failure.message ?: "资产收集审批失败"
            }
        }
    }

    private suspend fun refreshCampaigns(currentApi: SpiritApi) {
        val projectId = selectedProjectId
        if (projectId.isBlank()) {
            campaigns.clear()
            return
        }
        val root = currentApi.get("/api/projects/${enc(projectId)}/asset-campaigns")
        campaigns.clear()
        campaigns += root.array("campaigns").map(::parseCampaign)
        if (campaigns.none { it.id == selectedCampaignId }) {
            selectedCampaignId = ""
            targets.clear()
            outputs.clear()
            eventJob?.cancel()
        }
    }

    private fun parseCampaign(raw: JsonElement): AssetCampaignRow {
        val item = raw.objectOrEmpty()
        val config = item.element("config")?.objectOrEmpty()
        val stats = item.element("stats")?.objectOrEmpty()
        val egress = config?.element("egress")?.objectOrEmpty()
        val approvals = item.array("approvals").map { value ->
            val row = value.objectOrEmpty()
            PendingApprovalItem(
                id = row.string("approval_id").ifBlank { row.string("id") },
                action = row.string("action"),
                purpose = row.string("purpose").ifBlank { row.string("detail") },
                detail = row.string("detail")
            )
        }
        return AssetCampaignRow(
            id = item.string("campaign_id"),
            projectId = item.string("project_id"),
            status = item.string("status"),
            targets = item.array("targets").map { it.toString().trim('"') },
            model = config?.string("model").orEmpty(),
            proxyPlanId = config?.string("proxy_plan_id").orEmpty().ifBlank { "direct" },
            proxyName = egress?.string("name").orEmpty(),
            commands = stats?.int("commands") ?: 0,
            candidates = stats?.int("candidates") ?: 0,
            assetsRevision = stats?.long("assets_revision") ?: 0,
            error = item.string("error"),
            approvals = approvals,
            createdAt = item.double("created_at"),
            startedAt = item.double("started_at"),
            finishedAt = item.double("finished_at"),
            rawJson = prettyJson.encodeToString(JsonElement.serializer(), raw)
        )
    }

    private fun connectEvents() {
        val currentApi = apiProvider() ?: return
        val campaignId = selectedCampaignId
        if (campaignId.isBlank()) return
        eventJob?.cancel()
        eventJob = scope.launch(Dispatchers.IO) {
            var reconnect = 0
            while (isActive && selectedCampaignId == campaignId) {
                var streamDone = false
                try {
                    connectionStatus = "正在连接输出…"
                    currentApi.openEventStream(
                        "/api/asset-campaigns/${enc(campaignId)}/events?after=0"
                    ).bufferedReader(StandardCharsets.UTF_8).use { reader ->
                        connectionStatus = "实时连接"
                        reconnect = 0
                        var eventType = ""
                        val data = StringBuilder()
                        while (isActive) {
                            val line = reader.readLine() ?: break
                            when {
                                line.isBlank() -> {
                                    if (data.isNotEmpty()) {
                                        handleEvent(eventType, data.toString(), campaignId)
                                    }
                                    if (eventType == "done" || eventType == "deleted") {
                                        streamDone = true
                                        break
                                    }
                                    eventType = ""
                                    data.clear()
                                }
                                line.startsWith("event:") -> eventType = line.substringAfter(':').trim()
                                line.startsWith("data:") -> {
                                    if (data.isNotEmpty()) data.append('\n')
                                    data.append(line.substringAfter(':').trimStart())
                                }
                            }
                        }
                    }
                    if (streamDone) break
                } catch (failure: Exception) {
                    if (!isActive || selectedCampaignId != campaignId) break
                    connectionStatus = "输出连接中断，正在重连…"
                    reconnect += 1
                    delay((reconnect.coerceAtMost(5) * 1000).toLong())
                }
            }
        }
    }

    private suspend fun handleEvent(type: String, data: String, campaignId: String) {
        if (selectedCampaignId != campaignId) return
        when (type) {
            "output" -> runCatching {
                val item = Json.parseToJsonElement(data).objectOrEmpty()
                val line = AssetOutputLine(
                    seq = item.int("seq"),
                    level = item.string("level"),
                    message = item.string("message"),
                    createdAt = item.double("created_at")
                )
                withContext(Dispatchers.Swing) {
                    if (outputs.none { it.seq == line.seq && it.message == line.message }) {
                        outputs += line
                        while (outputs.size > 2000) outputs.removeAt(0)
                    }
                }
            }
            "state" -> runCatching {
                val parsed = parseCampaign(Json.parseToJsonElement(data))
                withContext(Dispatchers.Swing) {
                    val index = campaigns.indexOfFirst { it.id == parsed.id }
                    if (index >= 0) campaigns[index] = parsed else campaigns += parsed
                    if (parsed.assetsRevision != 0L) loadDetails()
                }
            }
            "deleted" -> {
                connectionStatus = "批次已删除"
                loadDetails()
            }
            "done" -> connectionStatus = "输出已同步"
        }
    }

    private fun splitLines(value: String): List<String> =
        value.split('\n', ',', '，')
            .map(String::trim)
            .filter(String::isNotBlank)
            .distinct()

    private fun JsonList(values: List<String>) =
        JsonArray(values.map(::JsonPrimitive))

    private fun enc(value: String): String =
        URLEncoder.encode(value, StandardCharsets.UTF_8)
}
