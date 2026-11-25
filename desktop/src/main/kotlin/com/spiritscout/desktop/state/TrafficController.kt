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
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.net.URLEncoder
import java.nio.charset.StandardCharsets
import java.nio.file.Path

data class TrafficExchangeRow(
    val id: String,
    val method: String,
    val url: String,
    val status: String,
    val error: String,
    val durationMs: Double,
    val responseBytes: Long,
    val agent: String,
    val capturedAt: Double,
    val websocket: Boolean,
    val rawJson: String
)

data class TrafficCaptureRow(
    val captureId: String,
    val name: String,
    val status: String,
    val packetCount: Int,
    val error: String,
    val source: String,
    val limited: Boolean
)

data class TrafficPacketRow(
    val id: Long,
    val number: Int,
    val relativeTime: Double,
    val source: String,
    val sourcePort: Int?,
    val destination: String,
    val destinationPort: Int?,
    val protocol: String,
    val length: Int,
    val info: String
)

data class TrafficSummary(
    val total: Int = 0,
    val errors: Int = 0,
    val requestBytes: Long = 0,
    val responseBytes: Long = 0,
    val packetCount: Int = 0,
    val packetBytes: Long = 0
)

class TrafficController(
    private val apiProvider: () -> SpiritApi?,
    private val scope: CoroutineScope
) {
    private val prettyJson = Json { prettyPrint = true }
    private var sessionId = ""

    var loading by mutableStateOf(false)
        private set
    var detailLoading by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set
    var message by mutableStateOf("")
        private set
    var summary by mutableStateOf(TrafficSummary())
        private set
    var filters by mutableStateOf(TrafficFilters())
        private set
    var pageNumber by mutableStateOf(1)
        private set
    var hasPrevious by mutableStateOf(false)
        private set
    var hasNext by mutableStateOf(false)
        private set
    var selectedRecordId by mutableStateOf("")
        private set
    var detail by mutableStateOf<JsonElement?>(null)
        private set
    val rows = mutableStateListOf<TrafficExchangeRow>()
    val captures = mutableStateListOf<TrafficCaptureRow>()
    val packets = mutableStateListOf<TrafficPacketRow>()

    var selectedCaptureId by mutableStateOf("")
        private set
    var packetFilter by mutableStateOf("")
        private set
    var packetLoading by mutableStateOf(false)
        private set
    var packetError by mutableStateOf<String?>(null)
        private set
    var selectedPacketId by mutableStateOf<Long?>(null)
        private set
    var packetDetail by mutableStateOf<JsonElement?>(null)
        private set
    var streamDetail by mutableStateOf<JsonElement?>(null)
        private set
    var captureCapabilities by mutableStateOf<JsonElement?>(null)
        private set
    var proxyStatus by mutableStateOf<JsonElement?>(null)
        private set
    var proxyEnvironment by mutableStateOf("")
        private set
    var catalogJson by mutableStateOf<JsonElement?>(null)
        private set
    var actionBusy by mutableStateOf(false)
        private set

    private var before: Int? = null
    private var nextBefore: Int? = null
    private val beforeHistory = mutableListOf<Int?>()
    private var packetBefore: Int? = null
    private var packetNextBefore: Int? = null
    private val packetHistory = mutableListOf<Int?>()

    val currentSessionId: String
        get() = sessionId

    fun loadCatalog() {
        val currentApi = apiProvider() ?: return
        scope.launch {
            try {
                catalogJson = currentApi.get("/api/traffic")
            } catch (failure: Exception) {
                error = failure.message ?: "流量目录读取失败"
            }
        }
    }

    fun openSession(targetSessionId: String) {
        if (targetSessionId.isBlank()) return
        if (sessionId != targetSessionId) {
            resetPageState()
        }
        refresh(targetSessionId)
    }

    fun reset() {
        sessionId = ""
        rows.clear()
        captures.clear()
        packets.clear()
        loading = false
        detailLoading = false
        error = null
        message = ""
        summary = TrafficSummary()
        filters = TrafficFilters()
        pageNumber = 1
        hasPrevious = false
        hasNext = false
        before = null
        nextBefore = null
        beforeHistory.clear()
        selectedRecordId = ""
        detail = null
        selectedCaptureId = ""
        packetFilter = ""
        packetLoading = false
        packetError = null
        selectedPacketId = null
        packetDetail = null
        streamDetail = null
        packetBefore = null
        packetNextBefore = null
        packetHistory.clear()
        captureCapabilities = null
        proxyStatus = null
        proxyEnvironment = ""
        actionBusy = false
    }

    fun refresh(targetSessionId: String = sessionId) {
        val currentApi = apiProvider() ?: return
        if (targetSessionId.isBlank()) return
        val sessionChanged = targetSessionId != sessionId
        sessionId = targetSessionId
        if (sessionChanged) resetPageState()
        scope.launch {
            loading = true
            error = null
            try {
                coroutineScope {
                    val rowsRequest = async { loadRowsPage(currentApi, sessionId, before) }
                    val capturesRequest = async {
                        currentApi.get("/api/sessions/${enc(sessionId)}/traffic/captures")
                    }
                    val capabilitiesRequest = async {
                        runCatching { currentApi.get("/api/traffic/capabilities") }.getOrNull()
                    }
                    val proxyRequest = async {
                        runCatching { currentApi.get("/api/sessions/${enc(sessionId)}/traffic/proxy") }.getOrNull()
                    }
                    val data = rowsRequest.await()
                    parseRowsPage(data)
                    parseCaptures(capturesRequest.await())
                    captureCapabilities = capabilitiesRequest.await()
                    proxyStatus = proxyRequest.await()
                }
            } catch (failure: Exception) {
                error = failure.message ?: "流量读取失败"
            } finally {
                loading = false
            }
        }
    }

    fun applyFilters(next: TrafficFilters) {
        filters = next
        before = null
        nextBefore = null
        beforeHistory.clear()
        pageNumber = 1
        selectedRecordId = ""
        detail = null
        refresh()
    }

    fun nextPage() {
        val next = nextBefore ?: return
        beforeHistory += before
        before = next
        pageNumber += 1
        hasPrevious = beforeHistory.isNotEmpty()
        selectedRecordId = ""
        detail = null
        refresh()
    }

    fun previousPage() {
        if (beforeHistory.isEmpty()) return
        before = beforeHistory.removeAt(beforeHistory.lastIndex)
        pageNumber = (pageNumber - 1).coerceAtLeast(1)
        hasPrevious = beforeHistory.isNotEmpty()
        selectedRecordId = ""
        detail = null
        refresh()
    }

    fun loadDetail(recordId: String) {
        val currentApi = apiProvider() ?: return
        if (sessionId.isBlank() || recordId.isBlank()) return
        selectedRecordId = recordId
        scope.launch {
            detailLoading = true
            error = null
            try {
                detail = currentApi.get("/api/sessions/${enc(sessionId)}/traffic/${enc(recordId)}")
            } catch (failure: Exception) {
                error = failure.message ?: "流量详情读取失败"
                detail = null
            } finally {
                detailLoading = false
            }
        }
    }

    fun clearDetail() {
        selectedRecordId = ""
        detail = null
    }

    fun selectCapture(captureId: String) {
        selectedCaptureId = captureId
        packetBefore = null
        packetNextBefore = null
        packetHistory.clear()
        selectedPacketId = null
        packetDetail = null
        streamDetail = null
        loadPackets()
    }

    fun applyPacketFilter(value: String) {
        packetFilter = value
        packetBefore = null
        packetNextBefore = null
        packetHistory.clear()
        selectedPacketId = null
        packetDetail = null
        streamDetail = null
        loadPackets()
    }

    fun loadPackets() {
        val currentApi = apiProvider() ?: return
        if (sessionId.isBlank() || selectedCaptureId.isBlank()) return
        scope.launch {
            packetLoading = true
            packetError = null
            try {
                val path = buildString {
                    append("/api/sessions/${enc(sessionId)}/traffic/packets")
                    append("?capture_id=${enc(selectedCaptureId)}&limit=100&order=asc")
                    packetBefore?.let { append("&before=$it") }
                    if (packetFilter.isNotBlank()) append("&display_filter=${enc(packetFilter)}")
                }
                val root = currentApi.get(path).objectOrEmpty()
                packets.clear()
                packets += root.array("items").mapNotNull { raw ->
                    val item = raw.objectOrEmpty()
                    val id = item.longOrZero("id")
                    if (id <= 0) null else TrafficPacketRow(
                        id = id,
                        number = item.int("number"),
                        relativeTime = item.double("relative_time"),
                        source = item.string("source"),
                        sourcePort = item.int("source_port").takeIf { it > 0 },
                        destination = item.string("destination"),
                        destinationPort = item.int("destination_port").takeIf { it > 0 },
                        protocol = item.string("protocol"),
                        length = item.int("length"),
                        info = item.string("info")
                    )
                }
                packetNextBefore = if (root.boolean("has_more")) {
                    root.element("next_before")?.toString()?.toIntOrNull()
                } else {
                    null
                }
                message = if (packets.isEmpty()) "没有符合条件的数据包。" else "数据包未脱敏；加密负载不会自动变成明文。"
            } catch (failure: Exception) {
                packetError = failure.message ?: "数据包读取失败"
                packets.clear()
            } finally {
                packetLoading = false
            }
        }
    }

    fun nextPacketPage() {
        val next = packetNextBefore ?: return
        packetHistory += packetBefore
        packetBefore = next
        loadPackets()
    }

    fun previousPacketPage() {
        if (packetHistory.isEmpty()) return
        packetBefore = packetHistory.removeAt(packetHistory.lastIndex)
        loadPackets()
    }

    fun loadPacketDetail(packetId: Long) {
        val currentApi = apiProvider() ?: return
        if (sessionId.isBlank()) return
        selectedPacketId = packetId
        streamDetail = null
        scope.launch {
            packetLoading = true
            packetError = null
            try {
                packetDetail = currentApi.get(
                    "/api/sessions/${enc(sessionId)}/traffic/packets/$packetId"
                )
            } catch (failure: Exception) {
                packetError = failure.message ?: "数据包详情读取失败"
                packetDetail = null
            } finally {
                packetLoading = false
            }
        }
    }

    fun clearPacketDetail() {
        selectedPacketId = null
        packetDetail = null
        streamDetail = null
    }

    fun followPacketStream(protocol: String, stream: Int) {
        val currentApi = apiProvider() ?: return
        val capture = selectedCaptureId
        if (sessionId.isBlank() || capture.isBlank()) return
        scope.launch {
            packetLoading = true
            packetError = null
            try {
                streamDetail = currentApi.get(
                    "/api/sessions/${enc(sessionId)}/traffic/captures/${enc(capture)}/follow" +
                        "?protocol=${enc(protocol)}&stream=$stream"
                )
            } catch (failure: Exception) {
                packetError = failure.message ?: "流追踪失败"
            } finally {
                packetLoading = false
            }
        }
    }

    fun importCapture(path: Path) {
        val currentApi = apiProvider() ?: return
        if (sessionId.isBlank()) return
        scope.launch {
            actionBusy = true
            packetError = null
            try {
                currentApi.importTrafficCapture(sessionId, path)
                message = "流量附件已提交解析。"
                refresh()
            } catch (failure: Exception) {
                packetError = failure.message ?: "流量附件导入失败"
            } finally {
                actionBusy = false
            }
        }
    }

    fun startCapture(interfaceName: String, captureFilter: String, duration: Int) {
        val currentApi = apiProvider() ?: return
        if (sessionId.isBlank()) return
        scope.launch {
            actionBusy = true
            packetError = null
            try {
                currentApi.post(
                    "/api/sessions/${enc(sessionId)}/traffic/capture",
                    buildJsonObject {
                        put("interface", interfaceName)
                        put("capture_filter", captureFilter)
                        put("duration", duration.coerceIn(5, 600))
                    }.toString()
                )
                refresh()
            } catch (failure: Exception) {
                packetError = failure.message ?: "启动抓包失败"
            } finally {
                actionBusy = false
            }
        }
    }

    fun stopCapture() {
        val currentApi = apiProvider() ?: return
        if (sessionId.isBlank()) return
        scope.launch {
            actionBusy = true
            packetError = null
            try {
                currentApi.delete("/api/sessions/${enc(sessionId)}/traffic/capture")
                refresh()
            } catch (failure: Exception) {
                packetError = failure.message ?: "停止抓包失败"
            } finally {
                actionBusy = false
            }
        }
    }

    fun startProxy(upstream: String = "") {
        val currentApi = apiProvider() ?: return
        if (sessionId.isBlank()) return
        scope.launch {
            actionBusy = true
            try {
                proxyStatus = currentApi.post(
                    "/api/sessions/${enc(sessionId)}/traffic/proxy",
                    buildJsonObject { put("upstream", upstream.trim()) }.toString()
                )
                runCatching {
                    currentApi.get("/api/sessions/${enc(sessionId)}/traffic/proxy/environment")
                }.getOrNull()?.let { root ->
                    proxyEnvironment = root.objectOrEmpty().string("environment")
                }
            } catch (failure: Exception) {
                error = failure.message ?: "会话代理启动失败"
            } finally {
                actionBusy = false
            }
        }
    }

    fun stopProxy() {
        val currentApi = apiProvider() ?: return
        if (sessionId.isBlank()) return
        scope.launch {
            actionBusy = true
            try {
                proxyStatus = currentApi.delete(
                    "/api/sessions/${enc(sessionId)}/traffic/proxy"
                )
                proxyEnvironment = ""
            } catch (failure: Exception) {
                error = failure.message ?: "会话代理停止失败"
            } finally {
                actionBusy = false
            }
        }
    }

    private fun resetPageState() {
        before = null
        nextBefore = null
        beforeHistory.clear()
        pageNumber = 1
        hasPrevious = false
        hasNext = false
        selectedRecordId = ""
        detail = null
        selectedCaptureId = ""
        packetBefore = null
        packetNextBefore = null
        packetHistory.clear()
        selectedPacketId = null
        packetDetail = null
        streamDetail = null
    }

    private suspend fun loadRowsPage(api: SpiritApi, session: String, cursor: Int?): JsonElement {
        val path = buildString {
            append("/api/sessions/${enc(session)}/traffic?limit=50")
            append("&query=${enc(filters.query)}")
            append("&errors_only=${filters.errorsOnly}")
            append("&method=${enc(filters.method)}")
            append("&status=${enc(filters.status)}")
            append("&body=${enc(filters.body)}")
            cursor?.let { append("&before=$it") }
        }
        return api.get(path)
    }

    private fun parseRowsPage(root: JsonElement) {
        val obj = root.objectOrEmpty()
        rows.clear()
        rows += obj.array("items").map { raw ->
            val item = raw.objectOrEmpty()
            TrafficExchangeRow(
                id = item.string("id"),
                method = item.string("method"),
                url = item.string("url"),
                status = item.string("status"),
                error = item.string("error"),
                durationMs = item.double("duration_ms"),
                responseBytes = item.longOrZero("response_bytes"),
                agent = item.string("agent_id"),
                capturedAt = item.double("captured_at"),
                websocket = item.string("transport") == "WS",
                rawJson = prettyJson.encodeToString(JsonElement.serializer(), raw)
            )
        }
        val summaryObj = obj.element("summary")?.objectOrEmpty()
        summary = TrafficSummary(
            total = summaryObj?.int("total") ?: 0,
            errors = summaryObj?.int("errors") ?: 0,
            requestBytes = summaryObj?.longOrZero("request_bytes") ?: 0,
            responseBytes = summaryObj?.longOrZero("response_bytes") ?: 0,
            packetCount = summaryObj?.int("packet_count") ?: 0,
            packetBytes = summaryObj?.longOrZero("packet_bytes") ?: 0
        )
        nextBefore = if (obj.boolean("has_more")) {
            obj.element("next_before")?.toString()?.toIntOrNull()
        } else {
            null
        }
        hasNext = nextBefore != null
        hasPrevious = beforeHistory.isNotEmpty()
        message = when {
            rows.isNotEmpty() -> "点击一条记录查看请求、响应和原始证据。"
            filters != TrafficFilters() -> "没有符合筛选条件的流量。"
            else -> "尚无流量记录。"
        }
    }

    private fun parseCaptures(root: JsonElement) {
        captures.clear()
        captures += root.array("items").mapNotNull { raw ->
            val item = raw.objectOrEmpty()
            val id = item.string("capture_id")
            if (id.isBlank()) null else TrafficCaptureRow(
                captureId = id,
                name = item.string("name").ifBlank { id.take(8) },
                status = item.string("status"),
                packetCount = item.int("packet_count"),
                error = item.string("error"),
                source = item.string("source"),
                limited = item.boolean("limited")
            )
        }
        if (selectedCaptureId.isBlank() || captures.none { it.captureId == selectedCaptureId }) {
            selectedCaptureId = captures.firstOrNull()?.captureId.orEmpty()
            packets.clear()
            packetDetail = null
        }
        if (selectedCaptureId.isNotBlank() && packets.isEmpty() && !packetLoading) {
            loadPackets()
        }
    }

    private fun kotlinx.serialization.json.JsonObject.longOrZero(name: String): Long =
        element(name)?.toString()?.toLongOrNull() ?: 0

    private fun JsonElement.longOrZero(name: String): Long =
        objectOrEmpty().element(name)?.toString()?.toLongOrNull() ?: 0

    private fun enc(value: String): String =
        URLEncoder.encode(value, StandardCharsets.UTF_8)
}

data class TrafficFilters(
    val query: String = "",
    val method: String = "",
    val status: String = "",
    val body: String = "",
    val errorsOnly: Boolean = false
)
