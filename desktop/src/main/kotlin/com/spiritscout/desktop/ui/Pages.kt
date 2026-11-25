package com.spiritscout.desktop.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.ArrowBack
import androidx.compose.material.icons.outlined.AttachFile
import androidx.compose.material.icons.outlined.CheckCircle
import androidx.compose.material.icons.outlined.ChevronRight
import androidx.compose.material.icons.outlined.ContentPaste
import androidx.compose.material.icons.outlined.Description
import androidx.compose.material.icons.outlined.ErrorOutline
import androidx.compose.material.icons.outlined.FolderOpen
import androidx.compose.material.icons.outlined.Memory
import androidx.compose.material.icons.outlined.Lock
import androidx.compose.material.icons.outlined.ListAlt
import androidx.compose.material.icons.outlined.PauseCircle
import androidx.compose.material.icons.outlined.PlayArrow
import androidx.compose.material.icons.outlined.Search
import androidx.compose.material.icons.outlined.Send
import androidx.compose.material.icons.outlined.Speed
import androidx.compose.material.icons.outlined.StopCircle
import androidx.compose.material.icons.outlined.SwapHoriz
import androidx.compose.material.icons.outlined.Terminal
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
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
import androidx.compose.ui.unit.sp
import com.moriafly.salt.ui.Button
import com.moriafly.salt.ui.ButtonAppearance
import com.moriafly.salt.ui.ButtonIntent
import com.moriafly.salt.ui.Card
import com.moriafly.salt.ui.Icon
import com.moriafly.salt.ui.SaltTheme
import com.moriafly.salt.ui.Switcher
import com.moriafly.salt.ui.Text
import com.moriafly.salt.ui.UnstableSaltUiApi
import com.spiritscout.desktop.AppController
import com.spiritscout.desktop.model.MetricTone
import com.spiritscout.desktop.model.ResourceItem
import com.spiritscout.desktop.model.Section
import com.spiritscout.desktop.model.SessionItem
import com.spiritscout.desktop.model.TimelineItem
import com.spiritscout.desktop.model.TimelineKind
import com.spiritscout.desktop.model.WorkTask
import com.spiritscout.desktop.model.WorkspaceTab
import com.spiritscout.desktop.model.array
import com.spiritscout.desktop.model.element
import com.spiritscout.desktop.model.objectOrEmpty
import com.spiritscout.desktop.model.string
import javax.swing.JFileChooser
import java.net.URLEncoder
import java.nio.charset.StandardCharsets
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject

@OptIn(UnstableSaltUiApi::class)
@Composable
fun PageContent(controller: AppController, section: Section = controller.section) {
    when (section) {
        Section.DASHBOARD -> DashboardPage(controller)
        Section.TASKS -> TasksPage(controller)
        Section.WORKSPACE -> WorkspacePage(controller)
        Section.SETTINGS -> SettingsPage(controller)
        Section.ASSETS -> AssetCollectionPage(controller)
        Section.INTELLIGENCE -> AssetIntelligencePage(controller)
        Section.MODELS -> ModelsPage(controller)
        Section.SKILLS -> SkillsPage(controller)
        Section.MCP -> McpPage(controller)
        Section.PROJECTS -> ProjectsPage(controller)
        Section.BROWSER_ACCOUNTS -> BrowserAccountsPage(controller)
        Section.PROXIES -> ProxyPage(controller)
        Section.SCHEDULES -> SchedulesPage(controller)
        Section.TRAFFIC -> GlobalTrafficPage(controller)
        Section.AGENTS -> AgentsPage(controller)
        Section.LOCAL_TOOLS -> LocalToolsPage(controller)
        Section.EXPERIENCE -> ExperiencePage(controller)
        else -> ResourcePage(controller, controller.section)
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
fun LoginPage(controller: AppController) {
    var username by remember { mutableStateOf("spiritscout") }
    var password by remember { mutableStateOf("") }
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Card(Modifier.width(430.dp), color = SaltTheme.colors.subBackground) {
            Column(Modifier.padding(30.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                Box(
                    Modifier.size(46.dp).clip(RoundedCornerShape(12.dp))
                        .background(SaltTheme.colors.highlight),
                    contentAlignment = Alignment.Center
                ) {
                    Icon(Icons.Outlined.Lock, null, tint = SaltTheme.colors.onHighlight, modifier = Modifier.size(22.dp))
                }
                LocalizedText("登录灵枢控制台", style = SaltTheme.textStyles.largeTitle)
                LocalizedText(
                    "本机后端已启动，但配置了管理员凭据。请输入账号密码。",
                    style = SaltTheme.textStyles.sub,
                    color = SaltTheme.colors.subText
                )
                Column(verticalArrangement = Arrangement.spacedBy(7.dp)) {
                    LocalizedText("管理员", style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
                    SpiritTextField(username, { username = it }, "管理员用户名")
                }
                Column(verticalArrangement = Arrangement.spacedBy(7.dp)) {
                    LocalizedText("密码", style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
                    SpiritPasswordField(password, { password = it }, "管理员密码")
                }
                controller.loginError?.let {
                    LocalizedText(it, color = SaltTheme.colors.error, style = SaltTheme.textStyles.sub)
                }
                LocalizedButton(
                    onClick = { controller.login(username.trim(), password) },
                    text = "登录",
                    enabled = username.isNotBlank() && password.isNotBlank(),
                    modifier = Modifier.fillMaxWidth()
                )
            }
        }
    }
}

@Composable
private fun DashboardPage(controller: AppController) {
    LaunchedEffect(Unit) {
        while (isActive) {
            delay(15_000)
            controller.refreshCurrent()
        }
    }
    val error = controller.errors[Section.DASHBOARD]
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(28.dp),
        verticalArrangement = Arrangement.spacedBy(18.dp)
    ) {
        if (error != null) {
            item { ErrorBlock(error) }
        }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(7.dp)) {
                listOf(
                    "hour" to "近 1 小时",
                    "today" to "今天",
                    "7d" to "近 7 天",
                    "30d" to "近 30 天",
                    "all" to "全部"
                ).forEach { (value, label) ->
                    val active = controller.dashboardPeriod == value
                    Box(
                        modifier = Modifier
                            .clip(RoundedCornerShape(50))
                            .background(
                                if (active) SaltTheme.colors.highlight
                                else SaltTheme.colors.subBackground
                            )
                            .clickable { controller.chooseDashboardPeriod(value) }
                            .padding(horizontal = 12.dp, vertical = 7.dp)
                    ) {
                        LocalizedText(
                            label,
                            style = SaltTheme.textStyles.sub,
                            color = if (active) SaltTheme.colors.onHighlight else SaltTheme.colors.subText
                        )
                    }
                }
            }
        }
        item {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                controller.metrics.forEach { metric ->
                    MetricCard(metric, Modifier.weight(1f))
                }
            }
        }
        item {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(18.dp)
            ) {
                RecentSessionsCard(
                    sessions = controller.sessions.take(5),
                    onOpen = controller::openSession,
                    modifier = Modifier.weight(1.55f)
                )
                SystemPulseCard(controller, Modifier.weight(0.85f))
            }
        }
        item {
            DeliveryCard(controller)
        }
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun RecentSessionsCard(
    sessions: List<SessionItem>,
    onOpen: (SessionItem) -> Unit,
    modifier: Modifier = Modifier
) {
    Card(modifier = modifier.height(370.dp), color = SaltTheme.colors.subBackground) {
        Column(Modifier.fillMaxSize().padding(20.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                LocalizedText(
                    "最近任务",
                    style = SaltTheme.textStyles.main,
                    fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.weight(1f)
                )
                LocalizedText("${sessions.size} 个", style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
            }
            Spacer(Modifier.height(14.dp))
            if (sessions.isEmpty()) {
                EmptyState("还没有任务", "点击右上角「新任务」开始。")
            } else {
                LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    items(sessions, key = { it.id }) { session ->
                        CompactSessionRow(session, onClick = { onOpen(session) })
                    }
                }
            }
        }
    }
}

@Composable
private fun CompactSessionRow(session: SessionItem, onClick: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .clickable(onClick = onClick)
            .padding(horizontal = 12.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Box(
            modifier = Modifier.size(34.dp).clip(CircleShape)
                .background(SaltTheme.colors.highlight.copy(alpha = 0.12f)),
            contentAlignment = Alignment.Center
        ) {
            LocalizedText(session.mode.take(1).ifBlank { "任" }, color = SaltTheme.colors.highlight, fontWeight = FontWeight.Bold)
        }
        Column(Modifier.weight(1f)) {
            LocalizedText(session.title, maxLines = 1, overflow = TextOverflow.Ellipsis, fontWeight = FontWeight.Medium)
            LocalizedText(
                listOf(session.target, session.createdAt).filter { it.isNotBlank() }.joinToString(" · "),
                style = SaltTheme.textStyles.sub,
                color = SaltTheme.colors.subText,
                maxLines = 1
            )
        }
        StatusPill(session.stateLabel, sessionStatusColor(session))
        Icon(Icons.Outlined.ChevronRight, null, modifier = Modifier.size(16.dp), tint = SaltTheme.colors.subText)
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun SystemPulseCard(controller: AppController, modifier: Modifier = Modifier) {
    val system = controller.system
    Card(modifier = modifier.height(370.dp), color = SaltTheme.colors.subBackground) {
        Column(Modifier.fillMaxSize().padding(20.dp)) {
            LocalizedText("本机状态", style = SaltTheme.textStyles.main, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.height(16.dp))
            GaugeRow(Icons.Outlined.Speed, "CPU", system?.cpu ?: 0.0)
            Spacer(Modifier.height(14.dp))
            GaugeRow(Icons.Outlined.Memory, "内存", system?.memory ?: 0.0)
            Spacer(Modifier.height(22.dp))
            Box(Modifier.fillMaxWidth().height(1.dp).background(SaltTheme.colors.stroke))
            Spacer(Modifier.height(18.dp))
            InfoLine("后端", controller.backendUrl.ifBlank { "未连接" })
            Spacer(Modifier.height(10.dp))
            InfoLine("运行时", controller.runtimeName.ifBlank { "准备中" })
            Spacer(Modifier.height(10.dp))
            InfoLine("应用内存", "%.1f MB".format(system?.appMemoryMb ?: 0.0))
            Spacer(Modifier.height(10.dp))
            InfoLine("子进程", "${system?.processCount ?: 0} 个")
        }
    }
}

@Composable
private fun GaugeRow(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    label: String,
    percent: Double
) {
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        Icon(icon, null, modifier = Modifier.size(18.dp), tint = SaltTheme.colors.subText)
        LocalizedText(label, modifier = Modifier.width(42.dp), style = SaltTheme.textStyles.sub)
        Box(
            modifier = Modifier.weight(1f).height(7.dp).clip(RoundedCornerShape(50))
                .background(SaltTheme.colors.stroke)
        ) {
            Box(
                modifier = Modifier.fillMaxWidth((percent.coerceIn(0.0, 100.0) / 100.0).toFloat())
                    .fillMaxHeight()
                    .clip(RoundedCornerShape(50))
                    .background(
                        when {
                            percent >= 90 -> SaltTheme.colors.error
                            percent >= 70 -> SaltTheme.colors.warning
                            else -> SaltTheme.colors.highlight
                        }
                    )
            )
        }
        LocalizedText("%.0f%%".format(percent), style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
    }
}

@Composable
private fun InfoLine(label: String, value: String) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        LocalizedText(label, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText, modifier = Modifier.width(76.dp))
        LocalizedText(value, style = SaltTheme.textStyles.sub, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun DeliveryCard(controller: AppController) {
    val completed = controller.sessions.count { it.status == "completed" }
    val running = controller.sessions.count { it.status == "running" }
    Card(modifier = Modifier.fillMaxWidth(), color = SaltTheme.colors.subBackground) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(20.dp),
            horizontalArrangement = Arrangement.spacedBy(22.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Icon(
                Icons.Outlined.CheckCircle,
                null,
                tint = SaltTheme.colors.success,
                modifier = Modifier.size(28.dp)
            )
            Column(Modifier.weight(1f)) {
                LocalizedText("执行概况", fontWeight = FontWeight.SemiBold)
                LocalizedText(
                    "已完成 $completed 个，运行中 $running 个。任务详情可在工作区继续对话和查看证据。",
                    style = SaltTheme.textStyles.sub,
                    color = SaltTheme.colors.subText
                )
            }
            LocalizedButton(
                onClick = { controller.navigate(Section.TASKS) },
                text = "查看全部任务",
                appearance = ButtonAppearance.Subtle
            )
        }
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun TasksPage(controller: AppController) {
    var query by remember { mutableStateOf("") }
    val filtered = controller.sessions.filter {
        query.isBlank() || listOf(it.title, it.target, it.mode, it.stateLabel)
            .any { field -> field.contains(query, ignoreCase = true) }
    }
    val error = controller.errors[Section.TASKS]
    Column(Modifier.fillMaxSize().padding(28.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(14.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Box(Modifier.weight(1f)) {
                SpiritTextField(query, { query = it }, "搜索任务、目标或模式")
                Icon(
                    Icons.Outlined.Search,
                    null,
                    modifier = Modifier.align(Alignment.CenterEnd).padding(end = 14.dp).size(17.dp),
                    tint = SaltTheme.colors.subText
                )
            }
            StatusPill("${filtered.size} 个任务", SaltTheme.colors.highlight)
        }
        Spacer(Modifier.height(16.dp))
        if (error != null) {
            ErrorBlock(error)
            Spacer(Modifier.height(14.dp))
        }
        Card(Modifier.fillMaxSize(), color = SaltTheme.colors.subBackground) {
            if (controller.loading[Section.TASKS] == true && filtered.isEmpty()) {
                LoadingBlock()
            } else if (filtered.isEmpty()) {
                EmptyState("没有匹配的任务", "修改搜索词，或创建新任务。")
            } else {
                LazyColumn(
                    contentPadding = androidx.compose.foundation.layout.PaddingValues(12.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    items(filtered, key = { it.id }) { session ->
                        SessionCard(session, onClick = { controller.openSession(session) })
                    }
                }
            }
        }
    }
}

@Composable
private fun SessionCard(session: SessionItem, onClick: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(10.dp))
            .clickable(onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(14.dp)
    ) {
        Box(
            modifier = Modifier.size(42.dp).clip(RoundedCornerShape(10.dp))
                .background(SaltTheme.colors.highlight.copy(alpha = 0.12f)),
            contentAlignment = Alignment.Center
        ) {
            LocalizedText(session.mode.ifBlank { "任务" }, color = SaltTheme.colors.highlight, fontSize = 11.sp, fontWeight = FontWeight.SemiBold)
        }
        Column(Modifier.weight(1.4f)) {
            LocalizedText(session.title, fontWeight = FontWeight.Medium, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Spacer(Modifier.height(3.dp))
            LocalizedText(
                listOf(session.target, session.model).filter { it.isNotBlank() }.joinToString(" · "),
                style = SaltTheme.textStyles.sub,
                color = SaltTheme.colors.subText,
                maxLines = 1
            )
        }
        Column(Modifier.width(110.dp)) {
            StatusPill(session.stateLabel, sessionStatusColor(session))
        }
        Column(Modifier.width(120.dp)) {
            LocalizedText("Token ${formatNumber(session.tokens)}", style = SaltTheme.textStyles.sub)
            LocalizedText("${session.rounds} 轮 · ${session.createdAt}", style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
        }
        Icon(Icons.Outlined.ChevronRight, null, modifier = Modifier.size(18.dp), tint = SaltTheme.colors.subText)
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun WorkspacePage(controller: AppController) {
    var sessionManageMode by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(controller.selectedSession?.id) {
        while (isActive) {
            delay(3_000)
            controller.refreshCurrent()
        }
    }
    LaunchedEffect(controller.sideChildSessionId) {
        while (isActive && controller.sideChildSessionId.isNotBlank()) {
            delay(1_500)
            controller.refreshSideChat()
        }
    }
    val workspace = controller.workspace
    val session = controller.selectedSession
    Column(Modifier.fillMaxSize().padding(24.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            SpiritIconButton(Icons.Outlined.ArrowBack, "返回任务", controller::returnToTasks)
            Column(Modifier.weight(1f)) {
                LocalizedText(session?.title ?: "任务工作区", style = SaltTheme.textStyles.largeTitle)
                LocalizedText(
                    listOfNotNull(session?.target, session?.model, workspace?.session?.stateLabel)
                        .filter { it.isNotBlank() }.joinToString(" · "),
                    style = SaltTheme.textStyles.sub,
                    color = SaltTheme.colors.subText
                )
            }
            if (workspace != null) {
                StatusPill(workspace.session.stateLabel, sessionStatusColor(workspace.session))
                if (workspace.session.isSideSession) {
                    LocalizedButton(
                        onClick = controller::returnToSideParent,
                        text = "返回来源会话",
                        appearance = ButtonAppearance.Subtle
                    )
                }
                LocalizedButton(
                    onClick = controller::changeSessionModel,
                    text = "模型",
                    appearance = ButtonAppearance.Subtle
                )
                LocalizedButton(
                    onClick = { sessionManageMode = "rename" },
                    text = "重命名",
                    appearance = ButtonAppearance.Subtle
                )
                LocalizedButton(
                    onClick = {
                        controller.loadSessionProjectOptions()
                        sessionManageMode = "project"
                    },
                    text = "项目",
                    appearance = ButtonAppearance.Subtle
                )
                LocalizedButton(
                    onClick = { sessionManageMode = "delete" },
                    text = "删除",
                    appearance = ButtonAppearance.Subtle,
                    intent = ButtonIntent.Destructive
                )
                if (workspace.session.status == "running") {
                    LocalizedButton(
                        onClick = { controller.sessionAction(if (workspace.session.paused) "resume" else "pause") },
                        text = if (workspace.session.paused) "继续" else "暂停",
                        appearance = ButtonAppearance.Subtle,
                        leadingIcon = {
                            Icon(
                                if (workspace.session.paused) Icons.Outlined.PlayArrow else Icons.Outlined.PauseCircle,
                                null,
                                modifier = Modifier.size(16.dp)
                            )
                        }
                    )
                    LocalizedButton(
                        onClick = { controller.sessionAction("stop") },
                        text = "结束",
                        appearance = ButtonAppearance.Subtle,
                        intent = ButtonIntent.Destructive,
                        leadingIcon = {
                            Icon(Icons.Outlined.StopCircle, null, modifier = Modifier.size(16.dp))
                        }
                    )
                }
            }
        }
        Spacer(Modifier.height(12.dp))
        WorkspaceTabBar(
            selected = controller.workspaceTab,
            onSelect = controller::selectWorkspaceTab
        )
        Spacer(Modifier.height(12.dp))
        if (controller.workspaceError != null) {
            ErrorBlock(controller.workspaceError!!)
            Spacer(Modifier.height(12.dp))
        }
        Row(Modifier.fillMaxSize(), horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            if (controller.workspaceTab == WorkspaceTab.CHAT) {
                ConversationCard(controller, Modifier.weight(1f))
            } else {
                WorkspaceDataCard(controller, Modifier.weight(1f))
            }
            WorkspaceSidebar(controller, workspace?.tasks.orEmpty(), workspace?.let {
                WorkspaceStats(
                    it.layers,
                    it.findings,
                    it.vulnerabilities,
                    it.flags,
                    it.pendingApprovals.size,
                    it.pendingQuestions.size
                )
            }, Modifier.width(310.dp))
        }
    }
    sessionManageMode?.let { mode ->
        SessionManageWindow(controller, mode) { sessionManageMode = null }
    }
}

@Composable
private fun WorkspaceTabBar(selected: WorkspaceTab, onSelect: (WorkspaceTab) -> Unit) {
    LazyRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        items(WorkspaceTab.entries, key = { it.name }) { tab ->
            val active = tab == selected
            Box(
                modifier = Modifier
                    .clip(RoundedCornerShape(50))
                    .background(
                        if (active) SaltTheme.colors.highlight
                        else SaltTheme.colors.subBackground
                    )
                    .clickable { onSelect(tab) }
                    .padding(horizontal = 13.dp, vertical = 7.dp)
            ) {
                LocalizedText(
                    tab.title,
                    style = SaltTheme.textStyles.sub,
                    color = if (active) SaltTheme.colors.onHighlight else SaltTheme.colors.subText,
                    fontWeight = if (active) FontWeight.SemiBold else FontWeight.Normal
                )
            }
        }
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun WorkspaceDataCard(controller: AppController, modifier: Modifier = Modifier) {
    val tab = controller.workspaceTab
    val data = controller.workspaceTabJson
    Card(modifier.fillMaxHeight(), color = SaltTheme.colors.subBackground) {
        Column(Modifier.fillMaxSize()) {
            Row(
                modifier = Modifier.fillMaxWidth().padding(horizontal = 18.dp, vertical = 13.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                LocalizedText(tab.title, modifier = Modifier.weight(1f), fontWeight = FontWeight.SemiBold)
                if (controller.workspaceTabLoading) {
                    LocalizedText("同步中…", style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
                } else {
                    LocalizedText(
                        "每 3 秒同步",
                        style = SaltTheme.textStyles.sub,
                        color = SaltTheme.colors.subText
                    )
                }
                val sid = controller.selectedSession?.id
                if (sid != null && tab == WorkspaceTab.REPORT) {
                    LocalizedButton(
                        onClick = { controller.openBackendUrl("/api/sessions/${urlPart(sid)}/report/download") },
                        text = "下载报告",
                        appearance = ButtonAppearance.Subtle
                    )
                }
                if (sid != null && tab == WorkspaceTab.EVENTS) {
                    LocalizedButton(
                        onClick = { controller.openBackendUrl("/api/sessions/${urlPart(sid)}/audit/download") },
                        text = "导出审计",
                        appearance = ButtonAppearance.Subtle
                    )
                }
                if (sid != null && tab == WorkspaceTab.EXPERIENCE) {
                    LocalizedButton(
                        onClick = controller::distillSessionExperience,
                        text = "提炼经验",
                        appearance = ButtonAppearance.Subtle
                    )
                }
            }
            Box(Modifier.fillMaxWidth().height(1.dp).background(SaltTheme.colors.stroke))
            when {
                controller.workspaceTabError != null -> ErrorBlock(controller.workspaceTabError!!)
                controller.workspaceTabLoading && data == null -> LoadingBlock("正在加载${tab.title}…")
                data == null -> EmptyState("暂无数据", "当前标签页还没有可展示内容。")
                tab == WorkspaceTab.REPORT -> WorkspaceReport(data)
                tab == WorkspaceTab.RECORDS -> WorkspaceRecordsOverview(controller, data)
                tab in setOf(
                    WorkspaceTab.TOPOLOGY,
                    WorkspaceTab.ASSETS,
                    WorkspaceTab.OPPORTUNITIES,
                    WorkspaceTab.CHALLENGES,
                    WorkspaceTab.VULNERABILITIES,
                    WorkspaceTab.FLAGS,
                    WorkspaceTab.EXPERIENCE,
                    WorkspaceTab.TRAFFIC,
                    WorkspaceTab.BACKGROUND,
                    WorkspaceTab.EVENTS,
                    WorkspaceTab.DELIVERABLES,
                    WorkspaceTab.FILES
                ) -> WorkspaceDomainPage(controller, tab, data)
                else -> {
                    val items = extractWorkspaceItems(tab, data)
                    if (items.isEmpty()) {
                        EmptyState("暂无${tab.title}记录", "该会话当前没有返回条目。")
                    } else {
                        LazyColumn(
                            modifier = Modifier.fillMaxSize(),
                            contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
                            verticalArrangement = Arrangement.spacedBy(9.dp)
                        ) {
                            itemsIndexed(items) { index, item ->
                                WorkspaceJsonRow(controller, tab, index, item)
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun WorkspaceReport(data: JsonElement) {
    val root = data.objectOrEmpty()
    val markdown = root.string("markdown").ifBlank { root.string("content") }.ifBlank { data.toString() }
    MarkdownView(markdown, Modifier.fillMaxSize().padding(16.dp))
}

@Composable
private fun WorkspaceRecordsOverview(controller: AppController, data: JsonElement) {
    val root = data.objectOrEmpty()
    val session = root.element("session")?.objectOrEmpty()
    val tasks = root.array("tasks")
    val running = tasks.count { it.objectOrEmpty().string("status") == "running" }
    val events = root.array("activity").size + root.array("events").size
    val traffic = root.array("traffic").size + root.array("records").size
    val background = root.array("background_tasks").size + root.array("jobs").size

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)
    ) {
        LocalizedText(
            "运行记录只展示执行事实，不会改变会话状态。",
            style = SaltTheme.textStyles.sub,
            color = SaltTheme.colors.subText
        )
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            RecordSummary("会话状态", session?.string("status").orEmpty().ifBlank { "未知" })
            RecordSummary("运行中任务", running.toString())
            RecordSummary("执行任务", tasks.size.toString())
        }
        RecordSection(
            icon = Icons.Outlined.Terminal,
            title = "工具事件",
            detail = if (events > 0) "已读取 $events 条事件" else "查看工具名称、参数、结果与错误",
            onClick = { controller.selectWorkspaceTab(WorkspaceTab.EVENTS) }
        )
        RecordSection(
            icon = Icons.Outlined.SwapHoriz,
            title = "流量",
            detail = if (traffic > 0) "已读取 $traffic 条记录" else "查看 HTTP、WebSocket、PCAP 与数据包",
            onClick = { controller.selectWorkspaceTab(WorkspaceTab.TRAFFIC) }
        )
        RecordSection(
            icon = Icons.Outlined.ListAlt,
            title = "后台任务",
            detail = if (background > 0) "已读取 $background 个任务" else "查看 Shell 输出、退出状态和停止操作",
            onClick = { controller.selectWorkspaceTab(WorkspaceTab.BACKGROUND) }
        )
    }
}

@Composable
private fun RecordSummary(label: String, value: String) {
    Row(
        modifier = Modifier
            .clip(RoundedCornerShape(8.dp))
            .background(SaltTheme.colors.background.copy(alpha = 0.55f))
            .padding(horizontal = 12.dp, vertical = 9.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        LocalizedText(label, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
        LocalizedText(value, style = SaltTheme.textStyles.sub, fontWeight = FontWeight.SemiBold)
    }
}

@Composable
private fun RecordSection(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    title: String,
    detail: String,
    onClick: () -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(SaltTheme.colors.background.copy(alpha = 0.55f))
            .clickable(onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(13.dp)
    ) {
        Box(
            modifier = Modifier
                .size(34.dp)
                .clip(RoundedCornerShape(8.dp))
                .background(SaltTheme.colors.highlight.copy(alpha = 0.12f)),
            contentAlignment = Alignment.Center
        ) {
            Icon(icon, null, modifier = Modifier.size(18.dp), tint = SaltTheme.colors.highlight)
        }
        Column(Modifier.weight(1f)) {
            LocalizedText(title, fontWeight = FontWeight.Medium)
            LocalizedText(detail, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
        }
        Icon(Icons.Outlined.ChevronRight, null, modifier = Modifier.size(18.dp), tint = SaltTheme.colors.subText)
    }
}

@Composable
private fun WorkspaceJsonRow(
    controller: AppController,
    tab: WorkspaceTab,
    index: Int,
    item: JsonElement
) {
    val obj = item.objectOrEmpty()
    val title = listOf(
        "insight",
        "title",
        "name",
        "label",
        "asset",
        "url",
        "path",
        "task_id",
        "job_id",
        "vuln_id",
        "record_id",
        "type"
    ).firstNotNullOfOrNull { key -> obj.string(key).takeIf { it.isNotBlank() } }
        ?: "${tab.title} #${index + 1}"
    val detail = listOf(
        "context",
        "description",
        "text",
        "summary",
        "result_summary",
        "command",
        "endpoint",
        "message",
        "note",
        "status"
    ).firstNotNullOfOrNull { key -> obj.string(key).takeIf { it.isNotBlank() } }
        ?: JsonObject(emptyMap()).toString()
    val badge = listOf("status", "severity", "type", "level", "kind")
        .firstNotNullOfOrNull { key -> obj.string(key).takeIf { it.isNotBlank() } }

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(9.dp))
            .background(SaltTheme.colors.background.copy(alpha = 0.5f))
            .padding(horizontal = 14.dp, vertical = 11.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Column(Modifier.weight(1f)) {
            LocalizedText(title, fontWeight = FontWeight.Medium, maxLines = 1, overflow = TextOverflow.Ellipsis)
            if (detail.isNotBlank()) {
                LocalizedText(
                    detail,
                    style = SaltTheme.textStyles.sub,
                    color = SaltTheme.colors.subText,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis
                )
            }
        }
        badge?.let { StatusPill(it, SaltTheme.colors.highlight) }
        if (tab == WorkspaceTab.BACKGROUND) {
            val jobId = obj.string("job_id").ifBlank { obj.string("id") }
            if (jobId.isNotBlank()) {
                LocalizedButton(
                    onClick = { controller.stopBackgroundTask(jobId) },
                    text = "停止",
                    appearance = ButtonAppearance.Subtle,
                    intent = ButtonIntent.Destructive
                )
            }
        }
        if (tab in setOf(WorkspaceTab.FILES, WorkspaceTab.DELIVERABLES)) {
            val path = obj.string("path").ifBlank { obj.string("rel") }
            val sid = controller.selectedSession?.id
            if (path.isNotBlank() && sid != null) {
                LocalizedButton(
                    onClick = {
                        controller.openBackendUrl(
                            "/api/sessions/${urlPart(sid)}/artifacts/download?path=${urlPart(path)}"
                        )
                    },
                    text = "下载",
                    appearance = ButtonAppearance.Subtle
                )
            }
        }
    }
}

private fun urlPart(value: String): String =
    URLEncoder.encode(value, StandardCharsets.UTF_8)

private fun extractWorkspaceItems(tab: WorkspaceTab, data: JsonElement): List<JsonElement> {
    if (data is JsonArray) return data.toList()
    val root = data.objectOrEmpty()
    fun arrayOf(vararg names: String): List<JsonElement> =
        names.firstNotNullOfOrNull { name ->
            root.element(name)?.let { value ->
                when (value) {
                    is JsonArray -> value.toList()
                    is JsonObject -> listOf(value)
                    else -> null
                }
            }
        }.orEmpty()

    return when (tab) {
        WorkspaceTab.FILES,
        WorkspaceTab.DELIVERABLES -> arrayOf("items", "deliverables")
        WorkspaceTab.TOPOLOGY -> arrayOf("topology", "dag_nodes", "tasks")
        WorkspaceTab.ASSETS -> arrayOf("observed_evidence", "assets")
        WorkspaceTab.OPPORTUNITIES -> arrayOf("testing_opportunities", "opportunities")
        WorkspaceTab.CHALLENGES -> arrayOf("challenge_progress", "challenges")
        WorkspaceTab.VULNERABILITIES -> arrayOf("items", "vulns")
        WorkspaceTab.FLAGS -> arrayOf("flags", "items")
        WorkspaceTab.EXPERIENCE -> arrayOf("items", "experience")
        WorkspaceTab.TRAFFIC -> arrayOf("records", "sessions", "packets")
        WorkspaceTab.BACKGROUND -> arrayOf("items", "jobs", "tasks")
        WorkspaceTab.EVENTS -> arrayOf("items", "events", "activity")
        WorkspaceTab.CHAT,
        WorkspaceTab.RECORDS,
        WorkspaceTab.REPORT -> emptyList()
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun ConversationCard(controller: AppController, modifier: Modifier = Modifier) {
    val workspace = controller.workspace
    Card(modifier = modifier.fillMaxHeight(), color = SaltTheme.colors.subBackground) {
        Column(Modifier.fillMaxSize()) {
            Row(
                modifier = Modifier.fillMaxWidth().padding(horizontal = 18.dp, vertical = 14.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                LocalizedText("对话与证据", modifier = Modifier.weight(1f), fontWeight = FontWeight.SemiBold)
                if (workspace?.session?.isSideSession != true) {
                    LazyRow(
                        modifier = Modifier.widthIn(max = 460.dp),
                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        item {
                            LocalizedButton(
                                onClick = { controller.selectSideAgent("") },
                                text = "实况",
                                appearance = if (controller.sideActor.isBlank()) {
                                    ButtonAppearance.Filled
                                } else {
                                    ButtonAppearance.Subtle
                                }
                            )
                        }
                        items(controller.sideAgents, key = { it.actor }) { agent ->
                            LocalizedButton(
                                onClick = { controller.selectSideAgent(agent.actor) },
                                text = agent.label,
                                appearance = if (controller.sideActor == agent.actor) {
                                    ButtonAppearance.Filled
                                } else {
                                    ButtonAppearance.Subtle
                                }
                            )
                        }
                    }
                    if (controller.sideChildSessionId.isNotBlank()) {
                        Spacer(Modifier.width(6.dp))
                        LocalizedButton(
                            onClick = controller::openSideChildSession,
                            text = "展开会话",
                            appearance = ButtonAppearance.Subtle
                        )
                    }
                }
                if (controller.workspaceLoading) {
                    LocalizedText("同步中…", style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
                }
            }
            Box(Modifier.fillMaxWidth().height(1.dp).background(SaltTheme.colors.stroke))
            if (controller.sideActor.isNotBlank()) {
                SideChatBody(controller)
            } else if (workspace == null) {
                LoadingBlock("正在载入任务状态…")
            } else {
                LazyColumn(
                    modifier = Modifier.weight(1f),
                    contentPadding = androidx.compose.foundation.layout.PaddingValues(18.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp)
                ) {
                    items(workspace.timeline) { item -> TimelineBubble(item) }
                }
            }
            Box(Modifier.fillMaxWidth().height(1.dp).background(SaltTheme.colors.stroke))
            if (controller.pendingUploads.isNotEmpty()) {
                Row(
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 8.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    LocalizedText(
                        "附件 ${controller.pendingUploads.size}",
                        style = SaltTheme.textStyles.sub,
                        color = SaltTheme.colors.subText
                    )
                    controller.pendingUploads.take(3).forEach { upload ->
                        StatusPill(upload.name, SaltTheme.colors.highlight)
                    }
                    LocalizedButton(
                        onClick = controller::clearUploads,
                        text = "清除",
                        appearance = ButtonAppearance.Subtle
                    )
                }
            }
            Row(
                modifier = Modifier.fillMaxWidth().padding(14.dp),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
                verticalAlignment = Alignment.Bottom
            ) {
                SpiritIconButton(Icons.Outlined.AttachFile, "添加附件", {
                    val chooser = JFileChooser().apply {
                        isMultiSelectionEnabled = true
                        dialogTitle = "选择会话附件"
                    }
                    if (chooser.showOpenDialog(null) == JFileChooser.APPROVE_OPTION) {
                        controller.addUploads(chooser.selectedFiles.map { it.toPath() })
                    }
                })
                SpiritIconButton(Icons.Outlined.FolderOpen, "添加文件夹", {
                    val chooser = JFileChooser().apply {
                        fileSelectionMode = JFileChooser.DIRECTORIES_ONLY
                        dialogTitle = "选择会话文件夹"
                    }
                    if (chooser.showOpenDialog(null) == JFileChooser.APPROVE_OPTION) {
                        chooser.selectedFile?.toPath()?.let(controller::addFolderUploads)
                    }
                })
                SpiritIconButton(Icons.Outlined.ContentPaste, "粘贴剪贴板图片", controller::addClipboardImage)
                SpiritTextField(
                    value = if (controller.sideActor.isBlank()) {
                        controller.workspaceDraft
                    } else {
                        controller.sideDraft
                    },
                    onValueChange = if (controller.sideActor.isBlank()) {
                        controller::setDraft
                    } else {
                        controller::updateSideDraft
                    },
                    placeholder = if (controller.sideActor.isBlank()) {
                        "给灵枢补充线索，或布置下一步…"
                    } else {
                        "给当前子 Agent 发送独立旁路消息…"
                    },
                    modifier = Modifier.weight(1f),
                    singleLine = false
                )
                LocalizedButton(
                    onClick = if (controller.sideActor.isBlank()) {
                        controller::sendWorkspaceMessage
                    } else {
                        controller::sendSideMessage
                    },
                    text = "发送",
                    enabled = if (controller.sideActor.isBlank()) {
                        controller.workspaceDraft.isNotBlank() || controller.pendingUploads.isNotEmpty()
                    } else {
                        !controller.sideBusy && (
                            controller.sideDraft.isNotBlank() ||
                                controller.pendingUploads.isNotEmpty()
                            )
                    },
                    leadingIcon = {
                        Icon(Icons.Outlined.Send, null, modifier = Modifier.size(16.dp))
                    }
                )
            }
        }
    }
}

@Composable
private fun ColumnScope.SideChatBody(controller: AppController) {
    val tasks = controller.workspace?.tasks.orEmpty().filter {
        it.agent == controller.sideActor
    }
    Column(Modifier.fillMaxWidth().weight(1f)) {
        if (controller.sideChildSessionId.isBlank()) {
            Row(
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                LocalizedText(
                    "引用任务",
                    style = SaltTheme.textStyles.sub,
                    color = SaltTheme.colors.subText
                )
                LazyRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    item {
                        LocalizedButton(
                            onClick = { controller.setSideTask("") },
                            text = "不引用",
                            appearance = if (controller.sideTaskId.isBlank()) {
                                ButtonAppearance.Filled
                            } else {
                                ButtonAppearance.Subtle
                            }
                        )
                    }
                    items(tasks, key = { it.id }) { task ->
                        LocalizedButton(
                            onClick = { controller.setSideTask(task.id) },
                            text = task.title.ifBlank { task.id },
                            appearance = if (controller.sideTaskId == task.id) {
                                ButtonAppearance.Filled
                            } else {
                                ButtonAppearance.Subtle
                            }
                        )
                    }
                }
            }
            Box(Modifier.fillMaxWidth().height(1.dp).background(SaltTheme.colors.stroke))
        }
        LazyColumn(
            modifier = Modifier.weight(1f),
            contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            if (controller.sideMessages.isEmpty()) {
                item {
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(8.dp))
                            .background(SaltTheme.colors.background.copy(alpha = 0.55f))
                            .padding(16.dp),
                        verticalArrangement = Arrangement.spacedBy(6.dp)
                    ) {
                        LocalizedText("和子 Agent 直接对话", fontWeight = FontWeight.SemiBold)
                        LocalizedText(
                            "旁路对话不会打断主任务；可引用一条已有任务记录后再发送第一条消息。",
                            style = SaltTheme.textStyles.sub,
                            color = SaltTheme.colors.subText
                        )
                    }
                }
            }
            items(controller.sideMessages) { message ->
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = if (message.role == "user") {
                        Arrangement.End
                    } else {
                        Arrangement.Start
                    }
                ) {
                    Column(
                        modifier = Modifier
                            .fillMaxWidth(0.86f)
                            .clip(RoundedCornerShape(9.dp))
                            .background(
                                if (message.role == "user") {
                                    SaltTheme.colors.highlight.copy(alpha = 0.1f)
                                } else {
                                    SaltTheme.colors.background.copy(alpha = 0.55f)
                                }
                            )
                            .padding(12.dp),
                        verticalArrangement = Arrangement.spacedBy(5.dp)
                    ) {
                        LocalizedText(
                            if (message.role == "user") "你" else "子 Agent",
                            style = SaltTheme.textStyles.sub,
                            color = if (message.role == "user") {
                                SaltTheme.colors.highlight
                            } else {
                                SaltTheme.colors.subText
                            },
                            fontWeight = FontWeight.SemiBold
                        )
                        SelectionContainer {
                            LocalizedText(message.content, style = SaltTheme.textStyles.paragraph)
                        }
                    }
                }
            }
            if (controller.sidePendingApprovals.isNotEmpty()) {
                item {
                    LocalizedText(
                        "待确认操作",
                        color = SaltTheme.colors.warning,
                        fontWeight = FontWeight.SemiBold
                    )
                }
                items(controller.sidePendingApprovals, key = { it.id }) { approval ->
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(8.dp))
                            .background(SaltTheme.colors.warning.copy(alpha = 0.08f))
                            .padding(12.dp),
                        verticalArrangement = Arrangement.spacedBy(7.dp)
                    ) {
                        LocalizedText(approval.action.ifBlank { "高风险动作" }, fontWeight = FontWeight.Medium)
                        LocalizedText(
                            approval.purpose.ifBlank { approval.detail.ifBlank { "请核实目标和影响。" } },
                            style = SaltTheme.textStyles.sub,
                            color = SaltTheme.colors.subText
                        )
                        Row(horizontalArrangement = Arrangement.spacedBy(7.dp)) {
                            LocalizedButton(
                                onClick = { controller.decideSideApproval(approval.id, true) },
                                text = "允许"
                            )
                            LocalizedButton(
                                onClick = { controller.decideSideApproval(approval.id, false) },
                                text = "拒绝",
                                appearance = ButtonAppearance.Subtle,
                                intent = ButtonIntent.Destructive
                            )
                        }
                    }
                }
            }
            if (controller.sidePendingQuestions.isNotEmpty()) {
                item {
                    LocalizedText(
                        "子 Agent 提问",
                        color = SaltTheme.colors.warning,
                        fontWeight = FontWeight.SemiBold
                    )
                }
                items(controller.sidePendingQuestions, key = { it.id }) { question ->
                    var answer by remember(question.id) { mutableStateOf("") }
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(8.dp))
                            .background(SaltTheme.colors.warning.copy(alpha = 0.08f))
                            .padding(12.dp),
                        verticalArrangement = Arrangement.spacedBy(7.dp)
                    ) {
                        LocalizedText(question.question.ifBlank { "智能体提问" }, fontWeight = FontWeight.Medium)
                        question.options.forEachIndexed { index, option ->
                            LocalizedButton(
                                onClick = { controller.answerSideQuestion(question.id, choice = index) },
                                text = option,
                                appearance = ButtonAppearance.Subtle
                            )
                        }
                        if (question.options.isEmpty() || !question.multiple) {
                            SpiritTextField(answer, { answer = it }, "自定义答复")
                            LocalizedButton(
                                onClick = {
                                    controller.answerSideQuestion(question.id, text = answer)
                                    answer = ""
                                },
                                text = "提交答复",
                                enabled = answer.isNotBlank(),
                                appearance = ButtonAppearance.Subtle
                            )
                        }
                    }
                }
            }
        }
        val status = when {
            controller.sideBusy -> "正在发送…"
            controller.sidePendingApprovals.isNotEmpty() ||
                controller.sidePendingQuestions.isNotEmpty() -> "有操作等待你确认"
            controller.sideStatus in setOf("running", "queued") -> "子 Agent 正在处理…"
            controller.sideStatus == "failed" -> "本轮回复失败，可补充消息重试。"
            else -> ""
        }
        if (status.isNotBlank() || controller.sideError != null) {
            Row(
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                if (status.isNotBlank()) {
                    LocalizedText(
                        status,
                        style = SaltTheme.textStyles.sub,
                        color = SaltTheme.colors.subText
                    )
                }
                controller.sideError?.let { error ->
                    LocalizedText(error, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.error)
                }
            }
        }
    }
}

@Composable
private fun TimelineBubble(item: TimelineItem) {
    val color = when (item.kind) {
        TimelineKind.USER -> SaltTheme.colors.highlight
        TimelineKind.MASTER -> SaltTheme.colors.text
        TimelineKind.AGENT -> SaltTheme.colors.warning
        TimelineKind.FINDING -> SaltTheme.colors.success
        TimelineKind.SYSTEM -> SaltTheme.colors.subText
    }
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = if (item.kind == TimelineKind.USER) Arrangement.End else Arrangement.Start
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth(0.82f)
                .clip(RoundedCornerShape(10.dp))
                .background(color.copy(alpha = 0.08f))
                .padding(14.dp)
        ) {
            LocalizedText(item.title, style = SaltTheme.textStyles.sub, color = color, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.height(5.dp))
            LocalizedText(item.body, style = SaltTheme.textStyles.paragraph)
        }
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun WorkspaceSidebar(
    controller: AppController,
    tasks: List<WorkTask>,
    stats: WorkspaceStats?,
    modifier: Modifier = Modifier
) {
    Column(modifier.fillMaxHeight(), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        val approvals = controller.workspace?.pendingApprovals.orEmpty()
        val questions = controller.workspace?.pendingQuestions.orEmpty()
        if (approvals.isNotEmpty() || questions.isNotEmpty()) {
            Card(
                Modifier.fillMaxWidth().heightIn(max = 300.dp),
                color = SaltTheme.colors.warning.copy(alpha = 0.08f)
            ) {
                Column(
                    Modifier.fillMaxWidth()
                        .verticalScroll(rememberScrollState())
                        .padding(14.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp)
                ) {
                    LocalizedText("需要你决定", fontWeight = FontWeight.SemiBold, color = SaltTheme.colors.warning)
                    approvals.forEach { approval ->
                        Column(
                            Modifier.fillMaxWidth()
                                .clip(RoundedCornerShape(8.dp))
                                .background(SaltTheme.colors.subBackground)
                                .padding(10.dp)
                        ) {
                            LocalizedText(approval.action.ifBlank { "高风险动作" }, fontWeight = FontWeight.Medium)
                            LocalizedText(
                                approval.purpose.ifBlank { approval.detail.ifBlank { "请核实目标和影响。" } },
                                style = SaltTheme.textStyles.sub,
                                color = SaltTheme.colors.subText
                            )
                            Spacer(Modifier.height(7.dp))
                            Row(horizontalArrangement = Arrangement.spacedBy(7.dp)) {
                                LocalizedButton(
                                    onClick = { controller.decideApproval(approval.id, true) },
                                    text = "允许"
                                )
                                LocalizedButton(
                                    onClick = { controller.decideApproval(approval.id, false) },
                                    text = "拒绝",
                                    appearance = ButtonAppearance.Subtle,
                                    intent = ButtonIntent.Destructive
                                )
                            }
                        }
                    }
                    questions.forEach { question ->
                        Column(
                            Modifier.fillMaxWidth()
                                .clip(RoundedCornerShape(8.dp))
                                .background(SaltTheme.colors.subBackground)
                                .padding(10.dp)
                        ) {
                            LocalizedText(question.question.ifBlank { "智能体提问" }, fontWeight = FontWeight.Medium)
                            LocalizedText(
                                question.agent,
                                style = SaltTheme.textStyles.sub,
                                color = SaltTheme.colors.subText
                            )
                            Spacer(Modifier.height(7.dp))
                            if (question.options.isNotEmpty() && !question.multiple) {
                                question.options.forEachIndexed { index, option ->
                                    Box(
                                        Modifier.fillMaxWidth()
                                            .clip(RoundedCornerShape(7.dp))
                                            .clickable { controller.answerQuestion(question.id, index) }
                                            .padding(vertical = 6.dp)
                                    ) {
                                        LocalizedText(option, style = SaltTheme.textStyles.sub)
                                    }
                                }
                            }
                            LocalizedButton(
                                onClick = { controller.answerQuestion(question.id) },
                                text = "自定义答复",
                                appearance = ButtonAppearance.Subtle
                            )
                        }
                    }
                }
            }
        }
        Card(Modifier.fillMaxWidth(), color = SaltTheme.colors.subBackground) {
            Column(Modifier.padding(18.dp)) {
                LocalizedText("执行摘要", fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.height(14.dp))
                if (stats == null) {
                    LocalizedText("等待状态…", style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
                } else {
                    StatPair("任务节点", tasks.size.toString())
                    StatPair("发现", stats.findings.toString())
                    StatPair("漏洞", stats.vulnerabilities.toString())
                    StatPair("Flag", stats.flags.toString())
                    StatPair("待确认", (stats.approvals + stats.questions).toString())
                }
            }
        }
        Card(Modifier.fillMaxWidth().weight(1f), color = SaltTheme.colors.subBackground) {
            Column(Modifier.fillMaxSize().padding(18.dp)) {
                LocalizedText("智能体任务", fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.height(12.dp))
                if (tasks.isEmpty()) {
                    LocalizedText("尚未派发子任务", style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
                } else {
                    LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        items(tasks, key = { it.id }) { task ->
                            Column(
                                Modifier.fillMaxWidth()
                                    .clip(RoundedCornerShape(8.dp))
                                    .background(SaltTheme.colors.background.copy(alpha = 0.55f))
                                    .padding(10.dp)
                            ) {
                                LocalizedText(task.title.ifBlank { task.agent }, maxLines = 1, fontWeight = FontWeight.Medium)
                                LocalizedText(
                                    "${task.agent} · ${task.status} · ${task.routesDone}/${task.routesTotal} 路线",
                                    style = SaltTheme.textStyles.sub,
                                    color = SaltTheme.colors.subText
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

private data class WorkspaceStats(
    val layers: Map<String, Long>,
    val findings: Int,
    val vulnerabilities: Int,
    val flags: Int,
    val approvals: Int,
    val questions: Int
)

@Composable
private fun StatPair(label: String, value: String) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(vertical = 5.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        LocalizedText(label, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText, modifier = Modifier.weight(1f))
        LocalizedText(value, style = SaltTheme.textStyles.main, fontWeight = FontWeight.SemiBold)
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun ResourcePage(controller: AppController, section: Section) {
    var query by remember(section) { mutableStateOf("") }
    val items = controller.resources[section].orEmpty()
    val filtered = items.filter {
        query.isBlank() || listOf(it.title, it.subtitle, it.meta, it.status)
            .any { value -> value.contains(query, ignoreCase = true) }
    }
    var selectedId by remember(section, items) { mutableStateOf(items.firstOrNull()?.id) }
    val selected = filtered.firstOrNull { it.id == selectedId } ?: filtered.firstOrNull()
    val error = controller.errors[section]
    val supportsNew = section in setOf(
        Section.SKILLS,
        Section.MCP,
        Section.MODELS,
        Section.PROJECTS,
        Section.SCHEDULES,
        Section.BROWSER_ACCOUNTS
    )
    val supportsEdit = supportsNew || section in setOf(Section.LOCAL_TOOLS, Section.AGENTS)
    val supportsDelete = section in setOf(
        Section.SKILLS,
        Section.MCP,
        Section.MODELS,
        Section.PROJECTS,
        Section.SCHEDULES,
        Section.BROWSER_ACCOUNTS,
        Section.EXPERIENCE
    )
    Row(Modifier.fillMaxSize().padding(26.dp), horizontalArrangement = Arrangement.spacedBy(16.dp)) {
        Card(Modifier.weight(1.3f).fillMaxHeight(), color = SaltTheme.colors.subBackground) {
            Column(Modifier.fillMaxSize()) {
                Row(
                    modifier = Modifier.fillMaxWidth().padding(16.dp),
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Box(Modifier.weight(1f)) {
                        SpiritTextField(query, { query = it }, "筛选 ${section.title}")
                        Icon(
                            Icons.Outlined.Search,
                            null,
                            modifier = Modifier.align(Alignment.CenterEnd).padding(end = 14.dp).size(17.dp),
                            tint = SaltTheme.colors.subText
                        )
                    }
                    StatusPill("${filtered.size} 项", SaltTheme.colors.highlight)
                    if (supportsNew && section != Section.LOCAL_TOOLS) {
                        LocalizedButton(
                            onClick = { controller.openResourceAction(section, null, "new") },
                            text = "新建"
                        )
                    }
                    if (section == Section.MODELS) {
                        LocalizedButton(
                            onClick = controller::openProviderAction,
                            text = "供应商",
                            appearance = ButtonAppearance.Subtle
                        )
                    }
                    if (supportsEdit && (section == Section.LOCAL_TOOLS || selected != null)) {
                        LocalizedButton(
                            onClick = {
                                controller.openResourceAction(
                                    section,
                                    if (section == Section.LOCAL_TOOLS) null else selected,
                                    "edit"
                                )
                            },
                            text = when (section) {
                                Section.LOCAL_TOOLS -> "配置"
                                Section.AGENTS -> "绑定模型"
                                else -> "编辑"
                            },
                            appearance = ButtonAppearance.Subtle
                        )
                    }
                    if (supportsDelete && selected != null) {
                        LocalizedButton(
                            onClick = { controller.openResourceAction(section, selected, "delete") },
                            text = "删除",
                            appearance = ButtonAppearance.Subtle,
                            intent = ButtonIntent.Destructive
                        )
                    }
                }
                ResourceExtraActions(controller, section, selected)
                Box(Modifier.fillMaxWidth().height(1.dp).background(SaltTheme.colors.stroke))
                when {
                    error != null -> ErrorBlock(error)
                    controller.loading[section] == true && filtered.isEmpty() -> LoadingBlock()
                    filtered.isEmpty() -> EmptyState("暂无数据", "当前接口没有返回可展示条目。")
                    else -> LazyColumn(
                        contentPadding = androidx.compose.foundation.layout.PaddingValues(10.dp),
                        verticalArrangement = Arrangement.spacedBy(7.dp)
                    ) {
                        items(filtered, key = { it.id.ifBlank { it.title } }) { item ->
                            ResourceRow(
                                item = item,
                                selected = item.id == selected?.id,
                                onClick = { selectedId = item.id }
                            )
                        }
                    }
                }
            }
        }
        ResourceInspector(section, selected, Modifier.weight(0.9f))
    }
}

@Composable
private fun ResourceExtraActions(
    controller: AppController,
    section: Section,
    selected: ResourceItem?
) {
    LazyRow(
        modifier = Modifier.fillMaxWidth(),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 16.dp, vertical = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(7.dp)
    ) {
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(7.dp)) {
                when (section) {
                    Section.ASSETS -> {
                        LocalizedButton(
                            onClick = controller::openAssetCampaignAction,
                            text = "新建资产采集",
                            appearance = ButtonAppearance.Subtle
                        )
                    }
                    Section.SKILLS -> {
                        LocalizedButton(
                            onClick = {
                                val chooser = JFileChooser().apply {
                                    dialogTitle = "选择 Skill 压缩包"
                                    fileFilter = javax.swing.filechooser.FileNameExtensionFilter(
                                        "Skill ZIP",
                                        "zip"
                                    )
                                }
                                if (chooser.showOpenDialog(null) == JFileChooser.APPROVE_OPTION) {
                                    controller.importSkillArchive(chooser.selectedFile.toPath())
                                }
                            },
                            text = "导入压缩包",
                            appearance = ButtonAppearance.Subtle
                        )
                    }
                    Section.MODELS -> {
                        if (selected != null) {
                            LocalizedButton(
                                onClick = { controller.testModel(selected) },
                                text = "测试模型",
                                appearance = ButtonAppearance.Subtle
                            )
                        }
                    }
                    Section.SCHEDULES -> {
                        if (selected != null) {
                            val enabled = runCatching {
                                Json.parseToJsonElement(selected.rawJson).jsonObject["enabled"]
                                    ?.toString()?.toBooleanStrict()
                            }.getOrNull() ?: true
                            LocalizedButton(
                                onClick = { controller.toggleSchedule(selected.id, !enabled) },
                                text = if (enabled) "停用" else "启用",
                                appearance = ButtonAppearance.Subtle
                            )
                        }
                    }
                    Section.BROWSER_ACCOUNTS -> {
                        if (selected != null) {
                            LocalizedButton(
                                onClick = { controller.browserAccountAction(selected, "open") },
                                text = "打开登录",
                                appearance = ButtonAppearance.Subtle
                            )
                            LocalizedButton(
                                onClick = { controller.browserAccountAction(selected, "capture") },
                                text = "保存登录态",
                                appearance = ButtonAppearance.Subtle
                            )
                            LocalizedButton(
                                onClick = { controller.browserAccountAction(selected, "clear") },
                                text = "清理缓存",
                                appearance = ButtonAppearance.Subtle,
                                intent = ButtonIntent.Destructive
                            )
                        }
                    }
                    Section.LOCAL_TOOLS -> {
                        LocalizedButton(
                            onClick = { controller.localToolsAction("refresh") },
                            text = "刷新索引",
                            appearance = ButtonAppearance.Subtle
                        )
                        LocalizedButton(
                            onClick = { controller.localToolsAction("cleanup") },
                            text = "清理暂存",
                            appearance = ButtonAppearance.Subtle,
                            intent = ButtonIntent.Destructive
                        )
                    }
                    Section.PROXIES -> {
                        LocalizedButton(
                            onClick = { controller.openProxyAction("subscribe") },
                            text = "添加订阅",
                            appearance = ButtonAppearance.Subtle
                        )
                        LocalizedButton(
                            onClick = { controller.openProxyAction("import") },
                            text = "导入配置",
                            appearance = ButtonAppearance.Subtle
                        )
                        if (selected != null) {
                            LocalizedButton(
                                onClick = { controller.openProxyAction("plan", selected) },
                                text = "建方案",
                                appearance = ButtonAppearance.Subtle
                            )
                            LocalizedButton(
                                onClick = { controller.openProxyAction("benchmark", selected) },
                                text = "测速",
                                appearance = ButtonAppearance.Subtle
                            )
                            LocalizedButton(
                                onClick = { controller.openProxyAction("delete", selected) },
                                text = "删除节点",
                                appearance = ButtonAppearance.Subtle,
                                intent = ButtonIntent.Destructive
                            )
                        }
                    }
                    Section.TRAFFIC -> {
                        if (selected != null) {
                            LocalizedButton(
                                onClick = { controller.openTrafficSession(selected) },
                                text = "查看会话流量",
                                appearance = ButtonAppearance.Subtle
                            )
                        }
                    }
                    Section.EXPERIENCE -> {
                        LocalizedButton(
                            onClick = controller::openExperienceMerge,
                            text = "整理相似经验",
                            appearance = ButtonAppearance.Subtle
                        )
                        LocalizedButton(
                            onClick = controller::openExperienceTools,
                            text = "打开快照工具",
                            appearance = ButtonAppearance.Subtle
                        )
                        if (selected != null) {
                            val sourceSession = runCatching {
                                Json.parseToJsonElement(selected.rawJson)
                                    .jsonObject["source_session"]?.toString()?.trim('"').orEmpty()
                            }.getOrDefault("")
                            if (sourceSession.isNotBlank()) {
                                LocalizedButton(
                                    onClick = { controller.openExperienceSource(selected) },
                                    text = "打开来源会话",
                                    appearance = ButtonAppearance.Subtle
                                )
                            }
                            val merged = runCatching {
                                Json.parseToJsonElement(selected.rawJson).jsonObject["merged_from"]
                                    ?.let { it.toString() != "[]" } ?: false
                            }.getOrDefault(false)
                            if (merged) {
                                LocalizedButton(
                                    onClick = { controller.restoreExperience(selected) },
                                    text = "撤销整理",
                                    appearance = ButtonAppearance.Subtle
                                )
                            }
                        }
                    }
                    else -> Unit
                }
            }
        }
    }
}

@Composable
private fun ResourceRow(item: ResourceItem, selected: Boolean, onClick: () -> Unit) {
    val background = if (selected) SaltTheme.colors.highlight.copy(alpha = 0.11f) else Color.Transparent
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(9.dp))
            .background(background)
            .clickable(onClick = onClick)
            .padding(horizontal = 13.dp, vertical = 11.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Box(
            Modifier.size(34.dp).clip(RoundedCornerShape(8.dp))
                .background(SaltTheme.colors.highlight.copy(alpha = 0.12f)),
            contentAlignment = Alignment.Center
        ) {
            LocalizedText(item.title.take(1).ifBlank { "·" }, color = SaltTheme.colors.highlight, fontWeight = FontWeight.Bold)
        }
        Column(Modifier.weight(1f)) {
            LocalizedText(item.title.ifBlank { item.id }, maxLines = 1, overflow = TextOverflow.Ellipsis, fontWeight = FontWeight.Medium)
            LocalizedText(
                item.subtitle.ifBlank { item.meta },
                style = SaltTheme.textStyles.sub,
                color = SaltTheme.colors.subText,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
        }
        if (item.status.isNotBlank()) {
            StatusPill(item.status, SaltTheme.colors.highlight)
        }
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun ResourceInspector(section: Section, item: ResourceItem?, modifier: Modifier = Modifier) {
    var showRaw by remember(item?.id) { mutableStateOf(false) }
    Card(modifier.fillMaxHeight(), color = SaltTheme.colors.subBackground) {
        if (item == null) {
            EmptyState("选择一项", "在左侧选择 ${section.title} 条目查看详情。")
        } else {
            Column(Modifier.fillMaxSize().padding(20.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    LocalizedText(
                        item.title.ifBlank { item.id },
                        modifier = Modifier.weight(1f),
                        style = SaltTheme.textStyles.largeTitle
                    )
                    LocalizedButton(
                        onClick = { showRaw = !showRaw },
                        text = if (showRaw) "结构化详情" else "高级原文",
                        appearance = ButtonAppearance.Subtle
                    )
                }
                Spacer(Modifier.height(6.dp))
                LocalizedText(item.subtitle.ifBlank { item.meta }, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
                Spacer(Modifier.height(16.dp))
                Box(Modifier.fillMaxWidth().height(1.dp).background(SaltTheme.colors.stroke))
                Spacer(Modifier.height(16.dp))
                if (showRaw) {
                    SelectionContainer {
                        LocalizedText(
                            item.rawJson,
                            modifier = Modifier.weight(1f).fillMaxWidth().verticalScroll(rememberScrollState()),
                            fontFamily = FontFamily.Monospace,
                            fontSize = 12.sp,
                            lineHeight = 18.sp,
                            color = SaltTheme.colors.text
                        )
                    }
                } else {
                    StructuredJsonDetails(item.rawJson, Modifier.weight(1f))
                }
            }
        }
    }
}

@Composable
private fun StructuredJsonDetails(rawJson: String, modifier: Modifier = Modifier) {
    val root = remember(rawJson) {
        runCatching { Json.parseToJsonElement(rawJson).jsonObject }.getOrNull()
    }
    if (root == null) {
        EmptyState("无法读取结构化字段", "可切换到高级原文查看后端返回内容。")
        return
    }
    val source = root["data"]?.takeIf { it is JsonObject }?.jsonObject ?: root
    Column(
        modifier = modifier.fillMaxWidth().verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        source.entries.forEach { (key, value) ->
            val sensitive = listOf("key", "secret", "token", "password", "cookie", "credential")
                .any { key.contains(it, ignoreCase = true) }
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(8.dp))
                    .background(SaltTheme.colors.background.copy(alpha = 0.5f))
                    .padding(horizontal = 12.dp, vertical = 9.dp),
                verticalAlignment = Alignment.Top,
                horizontalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                LocalizedText(
                    key,
                    modifier = Modifier.width(170.dp),
                    style = SaltTheme.textStyles.sub,
                    color = SaltTheme.colors.subText,
                    fontWeight = FontWeight.Medium
                )
                SelectionContainer {
                    LocalizedText(
                        if (sensitive) "••••••（已隐藏）" else structuredValue(value),
                        modifier = Modifier.weight(1f),
                        style = SaltTheme.textStyles.sub,
                        color = SaltTheme.colors.text
                    )
                }
            }
        }
    }
}

private fun structuredValue(value: JsonElement): String = when (value) {
    is JsonArray -> value.joinToString("\n") { item ->
        if (item is JsonObject) item.entries.joinToString(" · ") { (key, nested) ->
            "$key=${nested.toString().trim('"')}"
        } else {
            item.toString().trim('"')
        }
    }.ifBlank { "—" }
    is JsonObject -> value.entries.joinToString("\n") { (key, nested) ->
        "$key: ${nested.toString().trim('"')}"
    }.ifBlank { "—" }
    else -> value.toString().trim('"').ifBlank { "—" }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun SettingsPage(controller: AppController) {
    val system = controller.system
    var showStorageCleanup by remember { mutableStateOf(false) }
    var showUpdates by remember { mutableStateOf(false) }
    Row(Modifier.fillMaxSize().padding(26.dp), horizontalArrangement = Arrangement.spacedBy(16.dp)) {
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(14.dp)) {
            Card(Modifier.fillMaxWidth(), color = SaltTheme.colors.subBackground) {
                Column(Modifier.padding(20.dp)) {
                    LocalizedText("运行状态", fontWeight = FontWeight.SemiBold)
                    Spacer(Modifier.height(16.dp))
                    DetailLine("连接地址", controller.backendUrl)
                    DetailLine("Python 运行时", controller.runtimeName)
                    DetailLine("CPU", "%.1f%%".format(system?.cpu ?: 0.0))
                    DetailLine("内存", "%.1f%%".format(system?.memory ?: 0.0))
                    DetailLine("应用内存", "%.1f MB".format(system?.appMemoryMb ?: 0.0))
                    DetailLine("应用 CPU", "%.2f%%".format(system?.appCpu ?: 0.0))
                }
            }
            Card(Modifier.fillMaxWidth(), color = SaltTheme.colors.subBackground) {
                Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    LocalizedText("外观与通知", fontWeight = FontWeight.SemiBold)
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            LocalizedText("深色主题", fontWeight = FontWeight.Medium)
                            LocalizedText(
                                "切换后立即应用并持久化到本机桌面偏好。",
                                style = SaltTheme.textStyles.sub,
                                color = SaltTheme.colors.subText
                            )
                        }
                        Switcher(state = controller.darkTheme, onChange = { controller.toggleTheme() })
                    }
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            LocalizedText("界面语言", fontWeight = FontWeight.Medium)
                            LocalizedText(
                                "中文与英文界面文案即时切换。",
                                style = SaltTheme.textStyles.sub,
                                color = SaltTheme.colors.subText
                            )
                        }
                        LocalizedButton(
                            onClick = { controller.updateLanguage("zh-CN") },
                            text = "中文",
                            appearance = if (controller.language == "zh-CN") {
                                ButtonAppearance.Filled
                            } else {
                                ButtonAppearance.Subtle
                            }
                        )
                        Spacer(Modifier.width(6.dp))
                        LocalizedButton(
                            onClick = { controller.updateLanguage("en-US") },
                            text = "English",
                            appearance = if (controller.language == "en-US") {
                                ButtonAppearance.Filled
                            } else {
                                ButtonAppearance.Subtle
                            }
                        )
                    }
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            LocalizedText("动效偏好", fontWeight = FontWeight.Medium)
                            LocalizedText(
                                "控制页面切换和内容出现的动画强度。",
                                style = SaltTheme.textStyles.sub,
                                color = SaltTheme.colors.subText
                            )
                        }
                        listOf(
                            "system" to "跟随系统",
                            "soft" to "柔和",
                            "fast" to "快速",
                            "off" to "关闭"
                        ).forEach { (value, label) ->
                            LocalizedButton(
                                onClick = { controller.updateMotionPreference(value) },
                                text = label,
                                appearance = if (controller.motionPreference == value) {
                                    ButtonAppearance.Filled
                                } else {
                                    ButtonAppearance.Subtle
                                }
                            )
                            Spacer(Modifier.width(5.dp))
                        }
                    }
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            LocalizedText("系统通知", fontWeight = FontWeight.Medium)
                            LocalizedText(
                                "接收会话完成、失败和待处理提醒。",
                                style = SaltTheme.textStyles.sub,
                                color = SaltTheme.colors.subText
                            )
                        }
                        Switcher(
                            state = controller.notificationsEnabled,
                            onChange = controller::updateNotificationsEnabled
                        )
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        LocalizedButton(
                            onClick = controller::loadNotifications,
                            text = if (controller.notificationUnread > 0) {
                                "最近提醒 ${controller.notificationUnread}"
                            } else {
                                "最近提醒"
                            },
                            appearance = ButtonAppearance.Subtle
                        )
                        LocalizedButton(
                            onClick = controller::markNotificationsRead,
                            text = "全部已读",
                            appearance = ButtonAppearance.Subtle,
                            enabled = controller.notificationUnread > 0
                        )
                    }
                    controller.notificationJson?.let { notifications ->
                        val items = notifications.objectOrEmpty().array("items").take(8)
                        if (items.isEmpty()) {
                            LocalizedText(
                                "暂无最近提醒。",
                                style = SaltTheme.textStyles.sub,
                                color = SaltTheme.colors.subText
                            )
                        } else {
                            items.forEach { raw ->
                                val item = raw.objectOrEmpty()
                                val sessionId = item.string("session_id")
                                Row(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .clip(RoundedCornerShape(8.dp))
                                        .background(SaltTheme.colors.background.copy(alpha = 0.5f))
                                        .then(
                                            if (sessionId.isNotBlank()) {
                                                Modifier.clickable {
                                                    controller.openNotificationSession(sessionId)
                                                }
                                            } else {
                                                Modifier
                                            }
                                        )
                                        .padding(horizontal = 11.dp, vertical = 8.dp),
                                    verticalAlignment = Alignment.CenterVertically,
                                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                                ) {
                                    StatusPill(
                                        item.string("type").ifBlank { "提醒" },
                                        SaltTheme.colors.highlight
                                    )
                                    Column(Modifier.weight(1f)) {
                                        LocalizedText(
                                            item.string("title")
                                                .ifBlank { item.string("message") },
                                            style = SaltTheme.textStyles.sub
                                        )
                                        LocalizedText(
                                            item.string("detail")
                                                .ifBlank { sessionId },
                                            style = SaltTheme.textStyles.sub,
                                            color = SaltTheme.colors.subText,
                                            maxLines = 2
                                        )
                                    }
                                }
                            }
                        }
                    }
                }
            }
            Card(Modifier.fillMaxWidth(), color = SaltTheme.colors.subBackground) {
                Column(Modifier.padding(20.dp)) {
                    LocalizedText("本地数据", fontWeight = FontWeight.SemiBold)
                    Spacer(Modifier.height(10.dp))
                    LocalizedText(
                        "配置、会话数据库和密钥保存在用户目录，不进入程序安装目录。",
                        style = SaltTheme.textStyles.paragraph,
                        color = SaltTheme.colors.subText
                    )
                    Spacer(Modifier.height(16.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        LocalizedButton(
                            onClick = controller::openDataDirectory,
                            text = "打开数据目录",
                            leadingIcon = {
                                Icon(Icons.Outlined.FolderOpen, null, modifier = Modifier.size(16.dp))
                            }
                        )
                        LocalizedButton(
                            onClick = controller::openLogFile,
                            text = "打开日志",
                            appearance = ButtonAppearance.Subtle,
                            leadingIcon = {
                                Icon(Icons.Outlined.Description, null, modifier = Modifier.size(16.dp))
                            }
                        )
                    }
                }
            }
            Card(Modifier.fillMaxWidth(), color = SaltTheme.colors.subBackground) {
                Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    LocalizedText("系统维护", fontWeight = FontWeight.SemiBold)
                    Row(horizontalArrangement = Arrangement.spacedBy(9.dp)) {
                        LocalizedButton(
                            onClick = {
                                showUpdates = true
                                controller.checkUpdates()
                            },
                            text = "检查更新",
                            appearance = ButtonAppearance.Subtle
                        )
                        LocalizedButton(
                            onClick = controller::loadStorageOverview,
                            text = "存储概览",
                            appearance = ButtonAppearance.Subtle
                        )
                        LocalizedButton(
                            onClick = {
                                controller.loadStorageOverview()
                                showStorageCleanup = true
                            },
                            text = "存储清理",
                            appearance = ButtonAppearance.Subtle
                        )
                        LocalizedButton(
                            onClick = controller::openApiConsole,
                            text = "高级 API",
                            appearance = ButtonAppearance.Subtle
                        )
                        LocalizedButton(
                            onClick = controller::logout,
                            text = "退出登录",
                            appearance = ButtonAppearance.Subtle,
                            intent = ButtonIntent.Destructive
                        )
                    }
                    controller.settingsJson?.let { json ->
                        Box(Modifier.fillMaxWidth().heightIn(max = 260.dp)) {
                            StructuredJsonDetails(json.toString())
                        }
                    }
                }
            }
        }
        Card(Modifier.weight(1f).fillMaxHeight(), color = SaltTheme.colors.subBackground) {
            Column(Modifier.fillMaxSize().padding(18.dp)) {
                LocalizedText("桌面日志", fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.height(10.dp))
                SelectionContainer {
                    LocalizedText(
                        controller.logs.takeLast(300).joinToString("\n"),
                        modifier = Modifier.fillMaxSize().verticalScroll(rememberScrollState()),
                        fontFamily = FontFamily.Monospace,
                        fontSize = 12.sp,
                        lineHeight = 18.sp,
                        color = SaltTheme.colors.subText
                    )
                }
            }
        }
    }
    if (showStorageCleanup) {
        StorageCleanupWindow(controller) { showStorageCleanup = false }
    }
    if (showUpdates) {
        UpdateCenterWindow(controller) { showUpdates = false }
    }
}

@Composable
private fun DetailLine(label: String, value: String) {
    Row(Modifier.fillMaxWidth().padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
        LocalizedText(label, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText, modifier = Modifier.width(120.dp))
        LocalizedText(value.ifBlank { "—" }, style = SaltTheme.textStyles.main, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

@Composable
fun BootPage(message: String) {
    Column(
        modifier = Modifier.fillMaxSize(),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Box(
            Modifier.size(54.dp).clip(RoundedCornerShape(14.dp))
                .background(SaltTheme.colors.highlight),
            contentAlignment = Alignment.Center
        ) {
            LocalizedText("灵", color = SaltTheme.colors.onHighlight, fontSize = 24.sp, fontWeight = FontWeight.Bold)
        }
        Spacer(Modifier.height(18.dp))
        LocalizedText("正在启动灵枢", style = SaltTheme.textStyles.largeTitle)
        Spacer(Modifier.height(8.dp))
        LocalizedText(message, style = SaltTheme.textStyles.main, color = SaltTheme.colors.subText)
    }
}

@Composable
fun FatalPage(message: String) {
    Column(
        modifier = Modifier.fillMaxSize().padding(40.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Icon(Icons.Outlined.ErrorOutline, null, tint = SaltTheme.colors.error, modifier = Modifier.size(42.dp))
        Spacer(Modifier.height(16.dp))
        LocalizedText("灵枢没有启动成功", style = SaltTheme.textStyles.largeTitle)
        Spacer(Modifier.height(10.dp))
        LocalizedText(message, style = SaltTheme.textStyles.paragraph, color = SaltTheme.colors.subText)
    }
}

@Composable
private fun sessionStatusColor(session: SessionItem): Color {
    return when {
        session.paused -> SaltTheme.colors.warning
        session.status == "running" -> SaltTheme.colors.highlight
        session.status == "completed" -> SaltTheme.colors.success
        session.status == "failed" -> SaltTheme.colors.error
        session.status == "stopped" -> SaltTheme.colors.subText
        else -> SaltTheme.colors.warning
    }
}

private fun formatNumber(value: Long): String = when {
    value >= 1_000_000 -> "%.2fM".format(value / 1_000_000.0)
    value >= 1_000 -> "%.1fK".format(value / 1_000.0)
    else -> value.toString()
}
