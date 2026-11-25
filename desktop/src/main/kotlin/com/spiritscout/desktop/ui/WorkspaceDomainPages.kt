package com.spiritscout.desktop.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.ChevronRight
import androidx.compose.material.icons.outlined.Download
import androidx.compose.material.icons.outlined.OpenInNew
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.StopCircle
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.moriafly.salt.ui.Button
import com.moriafly.salt.ui.ButtonAppearance
import com.moriafly.salt.ui.ButtonIntent
import com.moriafly.salt.ui.Icon
import com.moriafly.salt.ui.SaltTheme
import com.moriafly.salt.ui.Text
import com.moriafly.salt.ui.UnstableSaltUiApi
import com.spiritscout.desktop.AppController
import com.spiritscout.desktop.model.WorkspaceTab
import com.spiritscout.desktop.model.array
import com.spiritscout.desktop.model.boolean
import com.spiritscout.desktop.model.element
import com.spiritscout.desktop.model.objectOrEmpty
import com.spiritscout.desktop.model.string
import com.spiritscout.desktop.state.TrafficFilters
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import java.net.URLEncoder
import java.nio.charset.StandardCharsets
import javax.swing.JFileChooser
import javax.swing.filechooser.FileNameExtensionFilter

@OptIn(UnstableSaltUiApi::class)
@Composable
fun WorkspaceDomainPage(
    controller: AppController,
    tab: WorkspaceTab,
    data: JsonElement
) {
    when (tab) {
        WorkspaceTab.TOPOLOGY -> TopologyWorkspacePage(data)
        WorkspaceTab.ASSETS -> AssetsWorkspacePage(data)
        WorkspaceTab.OPPORTUNITIES -> OpportunitiesWorkspacePage(data)
        WorkspaceTab.CHALLENGES -> ChallengesWorkspacePage(data)
        WorkspaceTab.VULNERABILITIES -> VulnerabilitiesWorkspacePage(data)
        WorkspaceTab.FLAGS -> FlagsWorkspacePage(data)
        WorkspaceTab.EXPERIENCE -> ExperienceWorkspacePage(data)
        WorkspaceTab.EVENTS -> EventsWorkspacePage(controller, data)
        WorkspaceTab.BACKGROUND -> BackgroundWorkspacePage(controller, data)
        WorkspaceTab.FILES,
        WorkspaceTab.DELIVERABLES -> FilesWorkspacePage(controller, tab, data)
        WorkspaceTab.TRAFFIC -> TrafficWorkspacePage(controller)
        else -> EmptyState("暂无专用视图", "该页面仍使用通用状态展示。")
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun TopologyWorkspacePage(data: JsonElement) {
    val items = workspaceItems(WorkspaceTab.TOPOLOGY, data)
    DomainList(
        items = items,
        emptyTitle = "暂无探索链路",
        emptyDescription = "会话尚未产生任务节点、事实或探索关系。"
    ) { item ->
        val obj = item.objectOrEmpty()
        val depth = obj.element("depth")?.toString()?.toIntOrNull()?.coerceIn(0, 12) ?: 0
        val title = firstValue(obj, "title", "task_type", "name", "asset", "id")
            .ifBlank { "任务节点" }
        val kind = firstValue(obj, "node_type", "kind", "type", "task_type")
        val status = firstValue(obj, "status", "state")
        val detail = firstValue(obj, "reason", "description", "result_summary", "summary", "next")
        DomainRecord(
            leading = {
                Spacer(Modifier.width((depth * 14).dp))
                Box(
                    Modifier
                        .size(9.dp)
                        .clip(CircleShape)
                        .background(statusColor(status))
                )
            },
            title = title,
            metadata = listOf(kind, status).filter(String::isNotBlank).joinToString(" · "),
            detail = detail,
            badge = status.takeIf(String::isNotBlank)
        )
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun AssetsWorkspacePage(data: JsonElement) {
    val items = workspaceItems(WorkspaceTab.ASSETS, data)
    DomainList(
        items = items,
        emptyTitle = "暂无资产记录",
        emptyDescription = "尚未观察到域名、URL、IP、应用或端口。"
    ) { item ->
        val obj = item.objectOrEmpty()
        val title = firstValue(obj, "value", "asset", "url", "endpoint", "title", "id")
            .ifBlank { "资产" }
        val assetType = firstValue(obj, "asset_type", "type", "kind")
        val scope = firstValue(obj, "scope_status", "verification_status", "status")
        val source = firstValue(obj, "source", "source_agent", "source_ref")
        val evidence = firstValue(obj, "summary", "description", "title", "attrs")
        DomainRecord(
            leading = { DomainIndex("A") },
            title = title,
            metadata = listOf(assetType, scope, source).filter(String::isNotBlank).joinToString(" · "),
            detail = evidence,
            badge = scope.takeIf(String::isNotBlank)
        )
    }
}

@Composable
private fun OpportunitiesWorkspacePage(data: JsonElement) {
    val items = workspaceItems(WorkspaceTab.OPPORTUNITIES, data)
    DomainList(
        items = items,
        emptyTitle = "暂无行动机会",
        emptyDescription = "当前没有具备收益依据和可执行条件的测试机会。"
    ) { item ->
        val obj = item.objectOrEmpty()
        DomainRecord(
            leading = { DomainIndex("O") },
            title = firstValue(obj, "title", "hypothesis", "opportunity", "name", "id")
                .ifBlank { "行动机会" },
            metadata = listOf(
                firstValue(obj, "status", "state"),
                firstValue(obj, "confidence", "score", "expected_value"),
                firstValue(obj, "blocked_reason", "condition")
            ).filter(String::isNotBlank).joinToString(" · "),
            detail = firstValue(obj, "rationale", "reason", "description", "summary", "next"),
            badge = firstValue(obj, "status", "state").takeIf(String::isNotBlank)
        )
    }
}

@Composable
private fun ChallengesWorkspacePage(data: JsonElement) {
    val items = workspaceItems(WorkspaceTab.CHALLENGES, data)
    DomainList(
        items = items,
        emptyTitle = "暂无赛题记录",
        emptyDescription = "该会话没有返回题目列表或题目进度。"
    ) { item ->
        val obj = item.objectOrEmpty()
        DomainRecord(
            leading = { DomainIndex("C") },
            title = firstValue(obj, "name", "title", "challenge", "challenge_id", "id")
                .ifBlank { "赛题" },
            metadata = listOf(
                firstValue(obj, "status", "state"),
                firstValue(obj, "platform", "source"),
                firstValue(obj, "solved", "progress", "points")
            ).filter(String::isNotBlank).joinToString(" · "),
            detail = firstValue(obj, "description", "summary", "hint", "address", "url"),
            badge = firstValue(obj, "status", "state").takeIf(String::isNotBlank)
        )
    }
}

@Composable
private fun VulnerabilitiesWorkspacePage(data: JsonElement) {
    val items = workspaceItems(WorkspaceTab.VULNERABILITIES, data)
    DomainList(
        items = items,
        emptyTitle = "暂无漏洞记录",
        emptyDescription = "当前会话没有返回漏洞或待验证发现。"
    ) { item ->
        val obj = item.objectOrEmpty()
        val severity = firstValue(obj, "severity", "level", "risk")
        DomainRecord(
            leading = { DomainIndex("V") },
            title = firstValue(obj, "title", "name", "vuln_type", "endpoint", "vuln_id", "id")
                .ifBlank { "漏洞" },
            metadata = listOf(
                severity,
                firstValue(obj, "status", "verification_status", "state"),
                firstValue(obj, "endpoint", "url", "asset")
            ).filter(String::isNotBlank).joinToString(" · "),
            detail = firstValue(obj, "summary", "description", "evidence", "impact", "reproduction"),
            badge = severity.takeIf(String::isNotBlank)
        )
    }
}

@Composable
private fun FlagsWorkspacePage(data: JsonElement) {
    val items = workspaceItems(WorkspaceTab.FLAGS, data)
    DomainList(
        items = items,
        emptyTitle = "暂无 Flag",
        emptyDescription = "尚未取得、提交或判定任何答案。"
    ) { item ->
        val obj = item.objectOrEmpty()
        val status = firstValue(obj, "status", "verdict", "accepted", "state")
        DomainRecord(
            leading = { DomainIndex("F") },
            title = firstValue(obj, "value", "flag", "answer", "title", "id")
                .ifBlank { "Flag" },
            metadata = listOf(
                status,
                firstValue(obj, "challenge", "task", "platform"),
                firstValue(obj, "submitted_at", "created_at", "source")
            ).filter(String::isNotBlank).joinToString(" · "),
            detail = firstValue(obj, "message", "detail", "description", "judgement"),
            badge = status.takeIf(String::isNotBlank)
        )
    }
}

@Composable
private fun ExperienceWorkspacePage(data: JsonElement) {
    val items = workspaceItems(WorkspaceTab.EXPERIENCE, data)
    DomainList(
        items = items,
        emptyTitle = "暂无经验记录",
        emptyDescription = "当前会话尚未提炼出可复用经验。"
    ) { item ->
        val obj = item.objectOrEmpty()
        DomainRecord(
            leading = { DomainIndex("E") },
            title = firstValue(obj, "insight", "title", "name", "id")
                .ifBlank { "经验" },
            metadata = listOf(
                firstValue(obj, "domain", "category", "type"),
                firstValue(obj, "tags", "source_session_id", "created_at"),
                firstValue(obj, "score", "confidence")
            ).filter(String::isNotBlank).joinToString(" · "),
            detail = firstValue(obj, "context", "description", "body", "lesson", "summary"),
            badge = firstValue(obj, "domain", "category").takeIf(String::isNotBlank)
        )
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun EventsWorkspacePage(controller: AppController, data: JsonElement) {
    var query by remember { mutableStateOf("") }
    val items = workspaceItems(WorkspaceTab.EVENTS, data)
    val filtered = filterItems(items, query) { obj ->
        listOf(
            firstValue(obj, "event", "action", "tool", "name", "type"),
            firstValue(obj, "status", "result", "error", "message"),
            firstValue(obj, "actor", "agent", "task_id")
        ).joinToString(" ")
    }
    DomainHeader(
        title = "工具事件",
        description = "核对实际工具调用、参数、结果和错误。"
    ) {
        DomainSearch(query, { query = it }, "搜索事件、工具、Agent…")
        val sid = controller.selectedSession?.id
        if (sid != null) {
            LocalizedButton(
                onClick = {
                    controller.openBackendUrl("/api/sessions/${urlPart(sid)}/audit/download")
                },
                text = "导出审计",
                appearance = ButtonAppearance.Subtle,
                leadingIcon = { Icon(Icons.Outlined.Download, null, modifier = Modifier.size(15.dp)) }
            )
        }
    }
    DomainList(
        items = filtered,
        emptyTitle = if (query.isBlank()) "暂无工具事件" else "没有匹配的事件",
        emptyDescription = "工具调用发生后会在这里显示参数、结果和错误。"
    ) { item ->
        val obj = item.objectOrEmpty()
        val status = firstValue(obj, "status", "result", "level")
        DomainRecord(
            leading = { DomainIndex("T") },
            title = firstValue(obj, "action", "event", "tool", "name", "type", "id")
                .ifBlank { "工具事件" },
            metadata = listOf(
                status,
                firstValue(obj, "actor", "agent"),
                firstValue(obj, "timestamp", "at", "created_at")
            ).filter(String::isNotBlank).joinToString(" · "),
            detail = firstValue(
                obj,
                "command", "arguments", "args", "result", "result_summary",
                "error", "message", "detail"
            ),
            badge = status.takeIf(String::isNotBlank)
        )
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun BackgroundWorkspacePage(controller: AppController, data: JsonElement) {
    val items = workspaceItems(WorkspaceTab.BACKGROUND, data)
    DomainList(
        items = items,
        emptyTitle = "暂无后台任务",
        emptyDescription = "长命令启动后会在这里显示输出、条件和退出状态。"
    ) { item ->
        val obj = item.objectOrEmpty()
        val jobId = firstValue(obj, "job_id", "id", "task_id")
        val status = firstValue(obj, "status", "state", "exit_code")
        DomainRecord(
            leading = { DomainIndex("B") },
            title = firstValue(obj, "title", "command", "name", "job_id", "id")
                .ifBlank { "后台任务" },
            metadata = listOf(
                status,
                firstValue(obj, "started_at", "created_at"),
                firstValue(obj, "condition", "wait_for", "exit_code")
            ).filter(String::isNotBlank).joinToString(" · "),
            detail = firstValue(obj, "output", "tail", "stdout", "stderr", "summary", "error"),
            badge = status.takeIf(String::isNotBlank),
            actions = {
                if (jobId.isNotBlank()) {
                    LocalizedButton(
                        onClick = { controller.stopBackgroundTask(jobId) },
                        text = "停止",
                        appearance = ButtonAppearance.Subtle,
                        intent = ButtonIntent.Destructive,
                        leadingIcon = {
                            Icon(Icons.Outlined.StopCircle, null, modifier = Modifier.size(15.dp))
                        }
                    )
                }
            }
        )
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun FilesWorkspacePage(
    controller: AppController,
    tab: WorkspaceTab,
    data: JsonElement
) {
    var query by remember { mutableStateOf("") }
    val items = workspaceItems(tab, data)
    val filtered = filterItems(items, query) { obj ->
        listOf(
            firstValue(obj, "name", "title", "path", "rel"),
            firstValue(obj, "kind", "type", "source", "category")
        ).joinToString(" ")
    }
    DomainHeader(
        title = "文件与证据档案",
        description = "查阅附件、脚本、工具证据、报告文件和记录版本。"
    ) {
        DomainSearch(query, { query = it }, "搜索文件名、来源、路径…")
        LocalizedButton(
            onClick = controller::refreshCurrent,
            text = "刷新",
            appearance = ButtonAppearance.Subtle,
            leadingIcon = { Icon(Icons.Outlined.Refresh, null, modifier = Modifier.size(15.dp)) }
        )
    }
    DomainList(
        items = filtered,
        emptyTitle = if (query.isBlank()) "暂无文件或档案" else "没有匹配的档案",
        emptyDescription = "会话生成或接收文件后会出现在这里。"
    ) { item ->
        val obj = item.objectOrEmpty()
        val path = firstValue(obj, "path", "rel", "name")
        val sid = controller.selectedSession?.id
        DomainRecord(
            leading = { DomainIndex("D") },
            title = firstValue(obj, "name", "title", "rel", "path", "id")
                .ifBlank { "档案条目" },
            metadata = listOf(
                firstValue(obj, "kind", "type", "category"),
                firstValue(obj, "size", "bytes"),
                firstValue(obj, "source", "source_agent", "created_at")
            ).filter(String::isNotBlank).joinToString(" · "),
            detail = firstValue(obj, "summary", "description", "rel", "path"),
            actions = {
                if (sid != null && path.isNotBlank()) {
                    LocalizedButton(
                        onClick = {
                            controller.openBackendUrl(
                                "/api/sessions/${urlPart(sid)}/artifacts/download?path=${urlPart(path)}"
                            )
                        },
                        text = "下载",
                        appearance = ButtonAppearance.Subtle,
                        leadingIcon = {
                            Icon(Icons.Outlined.Download, null, modifier = Modifier.size(15.dp))
                        }
                    )
                }
            }
        )
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
internal fun TrafficWorkspacePage(controller: AppController) {
    var mode by remember { mutableStateOf("HTTP") }
    Column(Modifier.fillMaxSize()) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                LocalizedText("会话流量与数据包", fontWeight = FontWeight.SemiBold)
                LocalizedText(
                    "任务交互、会话代理、PCAP 附件、协议树与原始字节。流量内容可能包含业务数据，原始证据未脱敏。",
                    style = SaltTheme.textStyles.sub,
                    color = SaltTheme.colors.subText
                )
            }
            LocalizedButton(
                onClick = { mode = "HTTP" },
                text = "HTTP / WS",
                appearance = if (mode == "HTTP") ButtonAppearance.Filled else ButtonAppearance.Subtle
            )
            LocalizedButton(
                onClick = { mode = "PACKETS" },
                text = "PCAP / 数据包",
                appearance = if (mode == "PACKETS") ButtonAppearance.Filled else ButtonAppearance.Subtle
            )
            LocalizedButton(
                onClick = { controller.traffic.refresh() },
                text = "刷新",
                appearance = ButtonAppearance.Subtle,
                leadingIcon = { Icon(Icons.Outlined.Refresh, null, modifier = Modifier.size(15.dp)) }
            )
        }
        Box(Modifier.fillMaxWidth().height(1.dp).background(SaltTheme.colors.stroke))
        if (mode == "HTTP") {
            HttpTrafficPanel(controller)
        } else {
            PacketTrafficPanel(controller)
        }
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun HttpTrafficPanel(controller: AppController) {
    val traffic = controller.traffic
    var query by remember { mutableStateOf("") }
    var method by remember { mutableStateOf("全部") }
    var status by remember { mutableStateOf("") }
    var body by remember { mutableStateOf("") }
    var errorsOnly by remember { mutableStateOf(false) }
    var proxyUpstream by remember { mutableStateOf("") }
    val methods = listOf("全部", "GET", "POST", "PUT", "PATCH", "DELETE", "CONNECT", "WS")
    val visibleRows = if (method == "全部") {
        traffic.rows
    } else if (method == "WS") {
        traffic.rows.filter { it.websocket }
    } else {
        traffic.rows.filter { it.method.equals(method, ignoreCase = true) }
    }

    Column(Modifier.fillMaxSize()) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 9.dp),
            horizontalArrangement = Arrangement.spacedBy(7.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Box(Modifier.weight(1.6f)) {
                SpiritTextField(query, { query = it }, "地址、方法或会话…")
            }
            Box(Modifier.width(110.dp)) {
                SpiritTextField(status, { status = it }, "200 / 4xx")
            }
            Box(Modifier.weight(1.2f)) {
                SpiritTextField(body, { body = it }, "正文关键词")
            }
            LocalizedButton(
                onClick = {
                    traffic.applyFilters(
                        TrafficFilters(
                            query = query.trim(),
                            method = method.takeUnless { it == "全部" || it == "WS" }.orEmpty(),
                            status = status.trim(),
                            body = body.trim(),
                            errorsOnly = errorsOnly
                        )
                    )
                },
                text = "筛选"
            )
        }
        LazyRow(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp),
            horizontalArrangement = Arrangement.spacedBy(6.dp)
        ) {
            items(methods) { value ->
                LocalizedButton(
                    onClick = { method = value },
                    text = value,
                    appearance = if (method == value) ButtonAppearance.Filled else ButtonAppearance.Subtle
                )
            }
            item {
                LocalizedButton(
                    onClick = { errorsOnly = !errorsOnly },
                    text = if (errorsOnly) "仅失败：开" else "仅失败：关",
                    appearance = if (errorsOnly) ButtonAppearance.Filled else ButtonAppearance.Subtle
                )
            }
        }
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp),
            horizontalArrangement = Arrangement.spacedBy(14.dp)
        ) {
            TrafficSummaryPill("交互", traffic.summary.total.toString())
            TrafficSummaryPill("失败", traffic.summary.errors.toString())
            TrafficSummaryPill("请求体", formatBytes(traffic.summary.requestBytes))
            TrafficSummaryPill("响应体", formatBytes(traffic.summary.responseBytes))
            TrafficSummaryPill("数据包", traffic.summary.packetCount.toString())
            Spacer(Modifier.weight(1f))
            if (traffic.proxyStatus?.objectOrEmpty()?.string("status") != "running") {
                Box(Modifier.width(220.dp)) {
                    SpiritTextField(proxyUpstream, { proxyUpstream = it }, "上游代理（可选）")
                }
            }
            LocalizedButton(
                onClick = {
                    if (traffic.proxyStatus?.objectOrEmpty()?.string("status") == "running") {
                        traffic.stopProxy()
                    } else {
                        traffic.startProxy(proxyUpstream)
                    }
                },
                text = if (traffic.proxyStatus?.objectOrEmpty()?.string("status") == "running") {
                    "停止录制代理"
                } else {
                    "启动录制代理"
                },
                appearance = ButtonAppearance.Subtle,
                enabled = !traffic.actionBusy
            )
            if (traffic.proxyStatus?.objectOrEmpty()?.string("status") == "running") {
                LocalizedButton(
                    onClick = {
                        val sid = traffic.currentSessionId
                        if (sid.isBlank()) return@LocalizedButton
                        controller.openBackendUrl("/api/sessions/${urlPart(sid)}/traffic/proxy/ca")
                    },
                    text = "下载 CA",
                    appearance = ButtonAppearance.Subtle,
                    leadingIcon = { Icon(Icons.Outlined.Download, null, modifier = Modifier.size(15.dp)) }
                )
            }
        }
        if (traffic.proxyEnvironment.isNotBlank()) {
            LocalizedText(
                traffic.proxyEnvironment,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 4.dp)
                    .clip(RoundedCornerShape(7.dp))
                    .background(SaltTheme.colors.background.copy(alpha = 0.5f))
                    .padding(9.dp),
                style = SaltTheme.textStyles.sub,
                fontFamily = FontFamily.Monospace,
                color = SaltTheme.colors.subText
            )
        }
        traffic.error?.let {
            LocalizedText(
                it,
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp),
                style = SaltTheme.textStyles.sub,
                color = SaltTheme.colors.error
            )
        }
        if (traffic.loading && visibleRows.isEmpty()) {
            LoadingBlock("正在读取流量…")
        } else if (visibleRows.isEmpty()) {
            EmptyState("暂无流量记录", traffic.message.ifBlank { "HTTP、HTTPS 和 WebSocket 请求会在这里显示。" })
        } else {
            LazyColumn(
                modifier = Modifier.weight(1f),
                contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(7.dp)
            ) {
                items(visibleRows, key = { it.id }) { row ->
                    val selected = traffic.selectedRecordId == row.id
                    DomainRecord(
                        leading = { DomainIndex(if (row.websocket) "WS" else row.method.ifBlank { "H" }) },
                        title = row.url.ifBlank { "流量记录 #${row.id}" },
                        metadata = listOf(
                            row.method,
                            row.status.takeIf(String::isNotBlank)?.let { "HTTP $it" }.orEmpty(),
                            "${row.durationMs.toInt()} ms",
                            formatBytes(row.responseBytes),
                            row.agent
                        ).filter(String::isNotBlank).joinToString(" · "),
                        detail = row.error.takeIf(String::isNotBlank)
                            ?: formatTrafficTime(row.capturedAt),
                        badge = row.error.ifBlank { row.status }.takeIf(String::isNotBlank),
                        onClick = { traffic.loadDetail(row.id) },
                        actions = {
                            if (selected) {
                                Icon(
                                    Icons.Outlined.ChevronRight,
                                    null,
                                    modifier = Modifier.size(17.dp),
                                    tint = SaltTheme.colors.highlight
                                )
                            }
                        }
                    )
                }
            }
        }
        if (traffic.detailLoading) {
            LocalizedText(
                "正在读取请求与响应…",
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 7.dp),
                style = SaltTheme.textStyles.sub,
                color = SaltTheme.colors.subText
            )
        }
        traffic.detail?.let { detail ->
            Box(
                Modifier
                    .fillMaxWidth()
                    .heightIn(max = 360.dp)
                    .padding(horizontal = 16.dp, vertical = 8.dp)
            ) {
                val obj = detail.objectOrEmpty()
                Column(
                    Modifier.fillMaxWidth().verticalScroll(rememberScrollState()),
                    verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(7.dp)
                    ) {
                        val sid = traffic.currentSessionId
                        if (sid.isNotBlank() &&
                            obj.element("original_available")?.toString()?.toBooleanStrictOrNull() == true
                        ) {
                            listOf("请求原文" to "request", "响应原文" to "response", "原始元信息" to "metadata")
                                .forEach { (label, direction) ->
                                    LocalizedButton(
                                        onClick = {
                                            controller.openBackendUrl(
                                                "/api/sessions/${urlPart(sid)}/traffic/" +
                                                    "${urlPart(traffic.selectedRecordId)}/original?direction=$direction"
                                            )
                                        },
                                        text = label,
                                        appearance = ButtonAppearance.Subtle,
                                        leadingIcon = {
                                            Icon(Icons.Outlined.Download, null, modifier = Modifier.size(15.dp))
                                        }
                                    )
                                }
                        }
                        Spacer(Modifier.weight(1f))
                        LocalizedButton(
                            onClick = traffic::clearDetail,
                            text = "收起",
                            appearance = ButtonAppearance.Subtle
                        )
                    }
                    TrafficDetail(obj)
                }
            }
        }
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            LocalizedText(
                "第 ${traffic.pageNumber} 页",
                style = SaltTheme.textStyles.sub,
                color = SaltTheme.colors.subText,
                modifier = Modifier.weight(1f)
            )
            LocalizedButton(
                onClick = { traffic.previousPage() },
                text = "上一页",
                appearance = ButtonAppearance.Subtle,
                enabled = traffic.hasPrevious
            )
            LocalizedButton(
                onClick = { traffic.nextPage() },
                text = "下一页",
                appearance = ButtonAppearance.Subtle,
                enabled = traffic.hasNext
            )
        }
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun PacketTrafficPanel(controller: AppController) {
    val traffic = controller.traffic
    val capabilities = traffic.captureCapabilities?.objectOrEmpty()
    val interfaces = capabilities?.array("interfaces").orEmpty().map { raw ->
        val item = raw.objectOrEmpty()
        item.string("id") to item.string("name").ifBlank { item.string("id") }
    }
    var interfaceId by remember { mutableStateOf("") }
    var captureFilter by remember { mutableStateOf("ip") }
    var duration by remember { mutableStateOf("60") }
    var displayFilter by remember { mutableStateOf(traffic.packetFilter) }
    var streamTextMode by remember { mutableStateOf(true) }

    Column(Modifier.fillMaxSize()) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 9.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            LocalizedButton(
                onClick = {
                    val chooser = JFileChooser().apply {
                        dialogTitle = "导入 PCAP / PCAPNG"
                        fileFilter = FileNameExtensionFilter("Wireshark 抓包 (*.pcap, *.pcapng)", "pcap", "pcapng")
                        isMultiSelectionEnabled = false
                    }
                    if (chooser.showOpenDialog(null) == JFileChooser.APPROVE_OPTION) {
                        chooser.selectedFile?.toPath()?.let(traffic::importCapture)
                    }
                },
                text = "导入抓包",
                appearance = ButtonAppearance.Subtle,
                enabled = !traffic.actionBusy,
                leadingIcon = { Icon(Icons.Outlined.OpenInNew, null, modifier = Modifier.size(15.dp)) }
            )
            Box(Modifier.weight(1f)) {
                SpiritTextField(captureFilter, { captureFilter = it }, "BPF 过滤器，例如 tcp port 443")
            }
            Box(Modifier.width(90.dp)) {
                SpiritTextField(duration, { duration = it }, "秒")
            }
            LocalizedButton(
                onClick = {
                    val chosen = interfaceId.ifBlank { interfaces.firstOrNull()?.first.orEmpty() }
                    if (chosen.isNotBlank()) {
                        traffic.startCapture(
                            chosen,
                            captureFilter.trim().ifBlank { "ip" },
                            duration.toIntOrNull() ?: 60
                        )
                    }
                },
                text = "开始实时抓包",
                enabled = capabilities?.boolean("live_available") == true &&
                    !traffic.actionBusy &&
                    interfaces.isNotEmpty()
            )
            LocalizedButton(
                onClick = traffic::stopCapture,
                text = "停止抓包",
                appearance = ButtonAppearance.Subtle,
                intent = ButtonIntent.Destructive,
                enabled = !traffic.actionBusy
            )
        }
        if (interfaces.isNotEmpty()) {
            LazyRow(
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp),
                horizontalArrangement = Arrangement.spacedBy(6.dp)
            ) {
                items(interfaces) { (id, name) ->
                    LocalizedButton(
                        onClick = { interfaceId = id },
                        text = "$id · $name",
                        appearance = if (interfaceId == id || (interfaceId.isBlank() && interfaces.first().first == id)) {
                            ButtonAppearance.Filled
                        } else {
                            ButtonAppearance.Subtle
                        }
                    )
                }
            }
        }
        if (capabilities != null && capabilities.boolean("available").not()) {
            LocalizedText(
                capabilities.string("error").ifBlank { "当前环境不可用 tshark。" },
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 6.dp),
                style = SaltTheme.textStyles.sub,
                color = SaltTheme.colors.warning
            )
        }
        if (traffic.captures.isNotEmpty()) {
            LazyRow(
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp),
                horizontalArrangement = Arrangement.spacedBy(6.dp)
            ) {
                items(traffic.captures, key = { it.captureId }) { capture ->
                    LocalizedButton(
                        onClick = { traffic.selectCapture(capture.captureId) },
                        text = "${capture.name} · ${capture.status} · ${capture.packetCount} 包",
                        appearance = if (traffic.selectedCaptureId == capture.captureId) {
                            ButtonAppearance.Filled
                        } else {
                            ButtonAppearance.Subtle
                        }
                    )
                }
            }
        }
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 7.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Box(Modifier.weight(1f)) {
                SpiritTextField(displayFilter, { displayFilter = it }, "Wireshark display filter，例如 dns 或 tcp.port == 443")
            }
            LocalizedButton(
                onClick = { traffic.applyPacketFilter(displayFilter.trim()) },
                text = "应用过滤器",
                enabled = traffic.selectedCaptureId.isNotBlank() && !traffic.packetLoading
            )
            val selectedCapture = traffic.captures.firstOrNull { it.captureId == traffic.selectedCaptureId }
            if (selectedCapture != null) {
                LocalizedButton(
                    onClick = {
                        val sid = traffic.currentSessionId
                        if (sid.isBlank()) return@LocalizedButton
                        controller.openBackendUrl(
                            "/api/sessions/${urlPart(sid)}/traffic/captures/" +
                                "${urlPart(selectedCapture.captureId)}/download"
                        )
                    },
                    text = "下载 PCAP",
                    appearance = ButtonAppearance.Subtle,
                    enabled = selectedCapture.status !in setOf("starting", "running"),
                    leadingIcon = { Icon(Icons.Outlined.Download, null, modifier = Modifier.size(15.dp)) }
                )
            }
        }
        traffic.packetError?.let {
            LocalizedText(
                it,
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp),
                style = SaltTheme.textStyles.sub,
                color = SaltTheme.colors.error
            )
        }
        if (traffic.packetLoading && traffic.packets.isEmpty()) {
            LoadingBlock("正在解析数据包…")
        } else if (traffic.selectedCaptureId.isBlank()) {
            EmptyState("暂无流量附件", "导入 PCAP/PCAPNG，或启动实时抓包后查看数据包。")
        } else if (traffic.packets.isEmpty()) {
            EmptyState("没有可显示的数据包", "附件可能仍在解析，或显示过滤器没有匹配结果。")
        } else {
            LazyColumn(
                modifier = Modifier.weight(1f),
                contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp)
            ) {
                items(traffic.packets, key = { it.id }) { packet ->
                    val selected = traffic.selectedPacketId == packet.id
                    DomainRecord(
                        leading = { DomainIndex(packet.protocol.ifBlank { "PKT" }) },
                        title = "#${packet.number}  ${packet.source}${packet.sourcePort?.let { ":$it" }.orEmpty()} → " +
                            "${packet.destination}${packet.destinationPort?.let { ":$it" }.orEmpty()}",
                        metadata = listOf(
                            packet.protocol,
                            "${"%.6f".format(packet.relativeTime)} s",
                            "${packet.length} 字节"
                        ).joinToString(" · "),
                        detail = packet.info,
                        onClick = { traffic.loadPacketDetail(packet.id) },
                        actions = {
                            if (selected) {
                                Icon(
                                    Icons.Outlined.ChevronRight,
                                    null,
                                    modifier = Modifier.size(17.dp),
                                    tint = SaltTheme.colors.highlight
                                )
                            }
                        }
                    )
                }
            }
        }
        traffic.packetDetail?.let { detail ->
            PacketDetail(
                detail = detail,
                textMode = streamTextMode,
                onTextModeChange = { streamTextMode = it },
                onFollow = traffic::followPacketStream,
                onClose = traffic::clearPacketDetail
            )
        }
        traffic.streamDetail?.let { stream ->
            PacketStream(stream, streamTextMode, { streamTextMode = it })
        }
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 7.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            LocalizedText(
                if (traffic.packetLoading) "正在读取数据包…" else "${traffic.packets.size} 包",
                style = SaltTheme.textStyles.sub,
                color = SaltTheme.colors.subText,
                modifier = Modifier.weight(1f)
            )
            LocalizedButton(
                onClick = traffic::previousPacketPage,
                text = "上一页",
                appearance = ButtonAppearance.Subtle,
                enabled = !traffic.packetLoading
            )
            LocalizedButton(
                onClick = traffic::nextPacketPage,
                text = "下一页",
                appearance = ButtonAppearance.Subtle,
                enabled = !traffic.packetLoading
            )
        }
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun PacketDetail(
    detail: JsonElement,
    textMode: Boolean,
    onTextModeChange: (Boolean) -> Unit,
    onFollow: (String, Int) -> Unit,
    onClose: () -> Unit
) {
    val obj = detail.objectOrEmpty()
    val packetId = obj.element("id")?.toString()?.toLongOrNull()
    val protocol = obj.string("protocol")
    val tcpStream = obj.element("tcp_stream")?.toString()?.toIntOrNull()
    val udpStream = obj.element("udp_stream")?.toString()?.toIntOrNull()
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(max = 420.dp)
            .padding(horizontal = 16.dp, vertical = 7.dp)
            .verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            LocalizedText(
                "数据包 #${obj.string("number").ifBlank { packetId?.toString().orEmpty() }} · $protocol",
                modifier = Modifier.weight(1f),
                fontWeight = FontWeight.SemiBold
            )
            LocalizedButton(
                onClick = { onTextModeChange(!textMode) },
                text = if (textMode) "显示 Hex" else "显示文本",
                appearance = ButtonAppearance.Subtle
            )
            LocalizedButton(
                onClick = onClose,
                text = "收起",
                appearance = ButtonAppearance.Subtle
            )
            tcpStream?.let {
                LocalizedButton(
                    onClick = { onFollow("tcp", it) },
                    text = "追踪 TCP 流 #$it",
                    appearance = ButtonAppearance.Subtle
                )
            }
            udpStream?.let {
                LocalizedButton(
                    onClick = { onFollow("udp", it) },
                    text = "追踪 UDP 流 #$it",
                    appearance = ButtonAppearance.Subtle
                )
            }
        }
        LocalizedText(
            listOf(
                "${obj.string("source")} → ${obj.string("destination")}",
                "${obj.string("length")} 字节",
                formatTrafficTime(obj.element("time")?.toString()?.toDoubleOrNull() ?: 0.0)
            ).filter(String::isNotBlank).joinToString(" · "),
            style = SaltTheme.textStyles.sub,
            color = SaltTheme.colors.subText
        )
        val payloadText = obj.string("payload_text")
            .ifBlank { "（无可显示文本负载；加密内容仍为密文）" }
        val rawHex = obj.string("raw_hex")
        LocalizedText(
            if (textMode) payloadText else hexDump(rawHex),
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(8.dp))
                .background(SaltTheme.colors.background.copy(alpha = 0.55f))
                .padding(12.dp),
            fontFamily = FontFamily.Monospace,
            style = SaltTheme.textStyles.sub
        )
        val layers = obj.element("layers")?.objectOrEmpty()
        if (layers != null) {
            layers.forEach { (layer, fields) ->
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(8.dp))
                        .background(SaltTheme.colors.background.copy(alpha = 0.45f))
                        .padding(11.dp),
                    verticalArrangement = Arrangement.spacedBy(4.dp)
                ) {
                    LocalizedText(layer.uppercase(), fontWeight = FontWeight.SemiBold)
                    fields.objectOrEmpty().forEach { (key, value) ->
                        LocalizedText(
                            "$key: ${value.toString().trim('"')}",
                            style = SaltTheme.textStyles.sub,
                            color = SaltTheme.colors.subText
                        )
                    }
                }
            }
        }
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun PacketStream(
    stream: JsonElement,
    textMode: Boolean,
    onTextModeChange: (Boolean) -> Unit
) {
    val obj = stream.objectOrEmpty()
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(max = 320.dp)
            .padding(horizontal = 16.dp, vertical = 7.dp)
            .verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            LocalizedText("流追踪", modifier = Modifier.weight(1f), fontWeight = FontWeight.SemiBold)
            LocalizedButton(
                onClick = { onTextModeChange(!textMode) },
                text = if (textMode) "显示 Hex" else "显示文本",
                appearance = ButtonAppearance.Subtle
            )
        }
        LocalizedText(
            obj.array("nodes").joinToString(" ↔ ") { it.toString().trim('"') },
            style = SaltTheme.textStyles.sub,
            color = SaltTheme.colors.subText
        )
        obj.array("segments").forEach { raw ->
            val segment = raw.objectOrEmpty()
            val direction = segment.element("direction")?.toString()?.toIntOrNull() ?: 0
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(8.dp))
                    .background(SaltTheme.colors.background.copy(alpha = 0.5f))
                    .padding(10.dp),
                verticalArrangement = Arrangement.spacedBy(4.dp)
            ) {
                LocalizedText(
                    if (direction == 0) "节点 0 → 节点 1" else "节点 1 → 节点 0",
                    style = SaltTheme.textStyles.sub,
                    color = SaltTheme.colors.subText
                )
                LocalizedText(
                    if (textMode) segment.string("text") else hexDump(segment.string("hex")),
                    fontFamily = FontFamily.Monospace,
                    style = SaltTheme.textStyles.sub
                )
            }
        }
    }
}

@Composable
private fun TrafficDetail(obj: JsonObject) {
    val blocks = listOf(
        "请求头" to headersText(obj.element("request_headers") ?: obj.element("headers")),
        "请求正文" to bodyText(obj.element("request_body") ?: obj.element("body")),
        "响应头" to headersText(obj.element("response_headers")),
        "响应正文" to bodyText(obj.element("response_body") ?: obj.element("response"))
    )
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(SaltTheme.colors.background.copy(alpha = 0.58f))
            .padding(13.dp),
        verticalArrangement = Arrangement.spacedBy(9.dp)
    ) {
        LocalizedText(
            listOf(
                firstValue(obj, "method"),
                firstValue(obj, "url"),
                firstValue(obj, "status").takeIf(String::isNotBlank)?.let { "状态 $it" }.orEmpty(),
                firstValue(obj, "source").takeIf(String::isNotBlank)?.let { "来源 $it" }.orEmpty(),
                firstValue(obj, "transport")
            ).filter(String::isNotBlank).joinToString(" · "),
            fontWeight = FontWeight.SemiBold
        )
        listOf(
            firstValue(obj, "capture_error"),
            firstValue(obj, "error")
        ).filter(String::isNotBlank).forEach { message ->
            LocalizedText(message, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.error)
        }
        blocks.filter { it.second.isNotBlank() }.forEach { (label, value) ->
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                LocalizedText(label, style = SaltTheme.textStyles.sub, fontWeight = FontWeight.SemiBold)
                LocalizedText(
                    value,
                    modifier = Modifier
                        .fillMaxWidth()
                        .heightIn(max = 180.dp)
                        .verticalScroll(rememberScrollState()),
                    fontFamily = FontFamily.Monospace,
                    style = SaltTheme.textStyles.sub
                )
            }
        }
        if (blocks.all { it.second.isBlank() }) {
            LocalizedText(
                "该记录未包含可展示的请求或响应正文。",
                style = SaltTheme.textStyles.sub,
                color = SaltTheme.colors.subText
            )
        }
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun TrafficSummaryPill(label: String, value: String) {
    Row(
        modifier = Modifier
            .clip(RoundedCornerShape(8.dp))
            .background(SaltTheme.colors.background.copy(alpha = 0.52f))
            .padding(horizontal = 10.dp, vertical = 7.dp),
        horizontalArrangement = Arrangement.spacedBy(6.dp)
    ) {
        LocalizedText(label, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
        LocalizedText(value, style = SaltTheme.textStyles.sub, fontWeight = FontWeight.SemiBold)
    }
}

private fun headersText(value: JsonElement?): String = when (value) {
    null -> ""
    is JsonArray -> value.joinToString("\n") { header ->
        when (header) {
            is JsonArray -> header.joinToString(": ") { it.toString().trim('"') }
            else -> header.toString().trim('"')
        }
    }
    is JsonObject -> value.entries.joinToString("\n") { (key, item) ->
        "$key: ${item.toString().trim('"')}"
    }
    else -> value.toString().trim('"').takeUnless { it == "null" }.orEmpty()
}

private fun bodyText(value: JsonElement?): String = when (value) {
    null -> ""
    is JsonObject -> {
        val text = firstValue(value, "text", "body", "content", "value")
        val details = listOf(
            firstValue(value, "encoding").takeIf(String::isNotBlank)?.let { "编码：$it" }.orEmpty(),
            if (firstValue(value, "truncated").toBooleanStrictOrNull() == true) "预览已截断" else ""
        ).filter(String::isNotBlank)
        if (details.isEmpty()) text else "$text\n\n[${details.joinToString(" · ")}]".trim()
    }
    is JsonArray -> value.joinToString("\n") { it.toString().trim('"') }
    else -> value.toString().trim('"').takeUnless { it == "null" }.orEmpty()
}

private fun formatBytes(value: Long): String = when {
    value < 1024 -> "$value B"
    value < 1024 * 1024 -> String.format("%.1f KiB", value / 1024.0)
    else -> String.format("%.1f MiB", value / 1048576.0)
}

private fun formatTrafficTime(value: Double): String {
    if (value <= 0) return ""
    return runCatching {
        java.time.Instant.ofEpochSecond(value.toLong())
            .atZone(java.time.ZoneId.systemDefault())
            .format(java.time.format.DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss"))
    }.getOrDefault(value.toString())
}

private fun hexDump(hex: String): String {
    val data = hex.chunked(2).filter { it.length == 2 }
    if (data.isEmpty()) return "（无原始字节）"
    return data.chunked(16).mapIndexed { index, row ->
        val offset = (index * 16).toString(16).padStart(8, '0')
        val hexPart = row.joinToString(" ").padEnd(47)
        val ascii = row.joinToString("") { byte ->
            val value = byte.toIntOrNull(16) ?: 0
            if (value in 32..126) value.toChar().toString() else "."
        }
        "$offset  $hexPart  $ascii"
    }.joinToString("\n")
}

@Composable
private fun DomainList(
    items: List<JsonElement>,
    emptyTitle: String,
    emptyDescription: String,
    row: @Composable (JsonElement) -> Unit
) {
    if (items.isEmpty()) {
        EmptyState(emptyTitle, emptyDescription)
        return
    }
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(9.dp)
    ) {
        items(items) { item -> row(item) }
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun DomainRecord(
    leading: @Composable () -> Unit,
    title: String,
    metadata: String,
    detail: String,
    badge: String? = null,
    onClick: (() -> Unit)? = null,
    actions: @Composable (() -> Unit)? = null
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(SaltTheme.colors.background.copy(alpha = 0.52f))
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)
            .padding(horizontal = 14.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(11.dp)
    ) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            leading()
        }
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
            LocalizedText(title, fontWeight = FontWeight.Medium, maxLines = 2, overflow = TextOverflow.Ellipsis)
            if (metadata.isNotBlank()) {
                LocalizedText(
                    metadata,
                    style = SaltTheme.textStyles.sub,
                    color = SaltTheme.colors.subText,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis
                )
            }
            if (detail.isNotBlank()) {
                LocalizedText(
                    detail,
                    style = SaltTheme.textStyles.sub,
                    color = SaltTheme.colors.subText,
                    maxLines = 3,
                    overflow = TextOverflow.Ellipsis
                )
            }
        }
        badge?.let { StatusPill(it, statusColor(it)) }
        actions?.invoke()
    }
}

@Composable
private fun DomainIndex(text: String) {
    Box(
        modifier = Modifier
            .size(30.dp)
            .clip(RoundedCornerShape(8.dp))
            .background(SaltTheme.colors.highlight.copy(alpha = 0.12f)),
        contentAlignment = Alignment.Center
    ) {
        LocalizedText(
            text.take(5),
            style = SaltTheme.textStyles.sub,
            color = SaltTheme.colors.highlight,
            fontWeight = FontWeight.SemiBold
        )
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun DomainHeader(
    title: String,
    description: String,
    actions: @Composable RowScope.() -> Unit
) {
    Column(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        LocalizedText(title, fontWeight = FontWeight.SemiBold)
        LocalizedText(description, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            actions()
        }
    }
    Box(Modifier.fillMaxWidth().height(1.dp).background(SaltTheme.colors.stroke))
}

@Composable
private fun RowScope.DomainSearch(value: String, onChange: (String) -> Unit, placeholder: String) {
    Box(Modifier.weight(1f)) {
        SpiritTextField(value, onChange, placeholder)
    }
}

internal fun workspaceItems(tab: WorkspaceTab, data: JsonElement): List<JsonElement> {
    if (data is JsonArray) return data.toList()
    val root = data.objectOrEmpty()
    val names = when (tab) {
        WorkspaceTab.TOPOLOGY -> arrayOf("topology", "nodes", "dag_nodes", "tasks", "process")
        WorkspaceTab.ASSETS -> arrayOf("observed_evidence", "assets", "items")
        WorkspaceTab.OPPORTUNITIES -> arrayOf("testing_opportunities", "opportunities", "items")
        WorkspaceTab.CHALLENGES -> arrayOf("challenge_progress", "challenges", "items")
        WorkspaceTab.VULNERABILITIES -> arrayOf("items", "vulns", "vulnerabilities")
        WorkspaceTab.FLAGS -> arrayOf("flags", "items")
        WorkspaceTab.EXPERIENCE -> arrayOf("items", "experience")
        WorkspaceTab.EVENTS -> arrayOf("items", "events", "activity")
        WorkspaceTab.BACKGROUND -> arrayOf("items", "jobs", "tasks", "background_tasks")
        WorkspaceTab.FILES,
        WorkspaceTab.DELIVERABLES -> arrayOf("items", "deliverables", "files")
        WorkspaceTab.TRAFFIC -> arrayOf("items", "records", "sessions", "packets")
        else -> emptyArray()
    }
    names.forEach { name ->
        root.element(name)?.let { value ->
            flattenItems(value).takeIf { it.isNotEmpty() }?.let { return it }
        }
    }
    return emptyList()
}

private fun flattenItems(value: JsonElement): List<JsonElement> = when (value) {
    is JsonArray -> value.toList()
    is JsonObject -> listOf(
        "items", "nodes", "records", "targets", "entries", "results"
    ).firstNotNullOfOrNull { key ->
        (value[key] as? JsonArray)?.toList()
    } ?: listOf(value)
    else -> emptyList()
}

private fun filterItems(
    items: List<JsonElement>,
    query: String,
    text: (JsonObject) -> String
): List<JsonElement> {
    if (query.isBlank()) return items
    return items.filter { text(it.objectOrEmpty()).contains(query, ignoreCase = true) }
}

private fun firstValue(obj: JsonObject, vararg keys: String): String {
    keys.forEach { key ->
        val value = obj[key] ?: return@forEach
        when (value) {
            is JsonArray -> {
                val text = value.joinToString("、") { it.toString().trim('"') }
                if (text.isNotBlank()) return text
            }
            is JsonObject -> {
                val text = value.toString()
                if (text.isNotBlank() && text != "{}") return text
            }
            else -> {
                val text = value.toString().trim('"')
                if (text.isNotBlank() && text != "null") return text
            }
        }
    }
    return ""
}

@Composable
private fun statusColor(status: String): Color {
    val value = status.lowercase()
    return when {
        value.contains("fail") || value.contains("error") || value.contains("reject") ||
            value in setOf("critical", "high") -> SaltTheme.colors.error
        value.contains("wait") || value.contains("pending") || value.contains("warn") ||
            value in setOf("medium", "queued") -> SaltTheme.colors.warning
        value.contains("done") || value.contains("complete") || value.contains("success") ||
            value.contains("accept") || value.contains("verified") -> SaltTheme.colors.success
        else -> SaltTheme.colors.highlight
    }
}

private fun urlPart(value: String): String =
    URLEncoder.encode(value, StandardCharsets.UTF_8)
