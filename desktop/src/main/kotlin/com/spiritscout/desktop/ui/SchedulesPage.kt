package com.spiritscout.desktop.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Add
import androidx.compose.material.icons.outlined.CalendarMonth
import androidx.compose.material.icons.outlined.Delete
import androidx.compose.material.icons.outlined.PauseCircle
import androidx.compose.material.icons.outlined.PlayArrow
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.DpSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.DialogWindow
import androidx.compose.ui.window.WindowPosition
import androidx.compose.ui.window.rememberDialogState
import com.moriafly.salt.ui.Button
import com.moriafly.salt.ui.ButtonAppearance
import com.moriafly.salt.ui.ButtonIntent
import com.moriafly.salt.ui.Card
import com.moriafly.salt.ui.Icon
import com.moriafly.salt.ui.SaltConfigs
import com.moriafly.salt.ui.SaltTheme
import com.moriafly.salt.ui.Text
import com.moriafly.salt.ui.UnstableSaltUiApi
import com.spiritscout.desktop.AppController
import com.spiritscout.desktop.state.ScheduleRow
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter

@OptIn(UnstableSaltUiApi::class)
@Composable
fun SchedulesPage(controller: AppController) {
    val catalog = controller.schedules
    var create by remember { mutableStateOf(false) }
    var deleteConfirm by remember { mutableStateOf("") }
    LaunchedEffect(Unit) {
        catalog.refresh()
        if (catalog.selectedId.isNotBlank()) catalog.loadRuns(catalog.selectedId)
    }
    LaunchedEffect(catalog.selectedId) {
        if (catalog.selectedId.isNotBlank()) catalog.loadRuns(catalog.selectedId)
    }

    Column(Modifier.fillMaxSize().padding(24.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                LocalizedText("自动任务", style = SaltTheme.textStyles.largeTitle)
                LocalizedText(
                    "独立创建定时任务，可绑定项目、模型、目标和授权范围；每次触发都会留下运行记录。",
                    style = SaltTheme.textStyles.sub,
                    color = SaltTheme.colors.subText
                )
            }
            LocalizedButton(
                onClick = catalog::refresh,
                text = "刷新",
                appearance = ButtonAppearance.Subtle,
                leadingIcon = { Icon(Icons.Outlined.Refresh, null, modifier = Modifier.size(15.dp)) }
            )
            Spacer(Modifier.width(8.dp))
            LocalizedButton(
                onClick = { create = true },
                text = "新建自动任务",
                leadingIcon = { Icon(Icons.Outlined.Add, null, modifier = Modifier.size(15.dp)) }
            )
        }
        catalog.error?.let { ErrorBlock(it) }
        if (catalog.message.isNotBlank()) {
            LocalizedText(catalog.message, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.success)
        }
        Row(Modifier.fillMaxSize(), horizontalArrangement = Arrangement.spacedBy(14.dp)) {
            Card(Modifier.width(520.dp).fillMaxHeight(), color = SaltTheme.colors.subBackground) {
                Column(Modifier.fillMaxSize()) {
                    Row(Modifier.fillMaxWidth().padding(15.dp), verticalAlignment = Alignment.CenterVertically) {
                        LocalizedText(
                            "${catalog.items.size} 个自动任务",
                            modifier = Modifier.weight(1f),
                            fontWeight = FontWeight.SemiBold
                        )
                        if (catalog.loading) {
                            LocalizedText("同步中…", style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
                        }
                    }
                    Box(Modifier.fillMaxWidth().height(1.dp).background(SaltTheme.colors.stroke))
                    if (catalog.items.isEmpty()) {
                        EmptyState("暂无自动任务", "创建后按指定时间触发独立会话。")
                    } else {
                        LazyColumn(
                            modifier = Modifier.fillMaxSize(),
                            contentPadding = androidx.compose.foundation.layout.PaddingValues(12.dp),
                            verticalArrangement = Arrangement.spacedBy(8.dp)
                        ) {
                            items(catalog.items, key = { it.id }) { item ->
                                ScheduleListRow(
                                    item = item,
                                    selected = catalog.selectedId == item.id,
                                    deleteConfirm = deleteConfirm == item.id,
                                    onSelect = { catalog.select(item.id) },
                                    onToggle = { catalog.toggle(item) },
                                    onDelete = {
                                        if (deleteConfirm == item.id) {
                                            catalog.delete(item)
                                            deleteConfirm = ""
                                        } else {
                                            deleteConfirm = item.id
                                        }
                                    }
                                )
                            }
                        }
                    }
                }
            }
            Card(Modifier.weight(1f).fillMaxHeight(), color = SaltTheme.colors.subBackground) {
                val selected = catalog.items.firstOrNull { it.id == catalog.selectedId }
                if (selected == null) {
                    EmptyState("选择一个自动任务", "查看任务上下文和最近运行结果。")
                } else {
                    Column(Modifier.fillMaxSize().padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                        LocalizedText(selected.name, style = SaltTheme.textStyles.largeTitle)
                        LocalizedText(
                            selected.message,
                            style = SaltTheme.textStyles.paragraph,
                            color = SaltTheme.colors.subText
                        )
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            ScheduleMetric("模式", selected.mode)
                            ScheduleMetric("项目", selected.projectId.ifBlank { "未分类" })
                            ScheduleMetric("模型", selected.model.ifBlank { "自动" })
                            ScheduleMetric("下次执行", formatScheduleTime(selected.nextRun))
                        }
                        LocalizedText(
                            listOf(
                                "目标 ${selected.target.ifBlank { "未指定" }}",
                                "范围 ${selected.scope.joinToString("、").ifBlank { "未指定" }}",
                                "间隔 ${selected.intervalSeconds?.let { "${it}s" } ?: "单次"}"
                            ).joinToString(" · "),
                            style = SaltTheme.textStyles.sub,
                            color = SaltTheme.colors.subText
                        )
                        selected.error.takeIf(String::isNotBlank)?.let {
                            LocalizedText(it, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.error)
                        }
                        Box(Modifier.fillMaxWidth().height(1.dp).background(SaltTheme.colors.stroke))
                        LocalizedText("最近运行", fontWeight = FontWeight.SemiBold)
                        if (catalog.runs.isEmpty()) {
                            LocalizedText("尚无运行记录。", style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
                        } else {
                            LazyColumn(
                                modifier = Modifier.weight(1f),
                                verticalArrangement = Arrangement.spacedBy(6.dp)
                            ) {
                                items(catalog.runs, key = { it.id }) { run ->
                                    Row(
                                        modifier = Modifier
                                            .fillMaxWidth()
                                            .clip(RoundedCornerShape(7.dp))
                                            .background(SaltTheme.colors.background.copy(alpha = 0.5f))
                                            .padding(10.dp),
                                        verticalAlignment = Alignment.CenterVertically,
                                        horizontalArrangement = Arrangement.spacedBy(8.dp)
                                    ) {
                                        LocalizedText(
                                            formatScheduleTime(run.due),
                                            modifier = Modifier.width(150.dp),
                                            style = SaltTheme.textStyles.sub
                                        )
                                        StatusPill(run.status.ifBlank { run.state }, SaltTheme.colors.highlight)
                                        LocalizedText(
                                            run.error.ifBlank { run.sessionId.ifBlank { "独立运行" } },
                                            style = SaltTheme.textStyles.sub,
                                            color = if (run.error.isBlank()) SaltTheme.colors.subText else SaltTheme.colors.error,
                                            modifier = Modifier.weight(1f)
                                        )
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    if (create) {
        ScheduleDialog(controller) { create = false }
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun ScheduleListRow(
    item: ScheduleRow,
    selected: Boolean,
    deleteConfirm: Boolean,
    onSelect: () -> Unit,
    onToggle: () -> Unit,
    onDelete: () -> Unit
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(
                if (selected) SaltTheme.colors.highlight.copy(alpha = 0.11f)
                else SaltTheme.colors.background.copy(alpha = 0.5f)
            )
            .clickable(onClick = onSelect)
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(5.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            LocalizedText(item.name, modifier = Modifier.weight(1f), fontWeight = FontWeight.SemiBold)
            StatusPill(if (item.enabled) "已启用" else "已停用", if (item.enabled) SaltTheme.colors.success else SaltTheme.colors.subText)
            StatusPill(item.state, scheduleStateColor(item.state))
        }
        LocalizedText(
            item.message,
            style = SaltTheme.textStyles.sub,
            color = SaltTheme.colors.subText,
            maxLines = 2
        )
        LocalizedText(
            "${formatScheduleTime(item.nextRun)} · ${item.mode} · ${item.model.ifBlank { "自动模型" }}",
            style = SaltTheme.textStyles.sub,
            color = SaltTheme.colors.subText
        )
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            LocalizedButton(
                onClick = onToggle,
                text = if (item.enabled) "停用" else "启用",
                appearance = ButtonAppearance.Subtle,
                leadingIcon = {
                    Icon(
                        if (item.enabled) Icons.Outlined.PauseCircle else Icons.Outlined.PlayArrow,
                        null,
                        modifier = Modifier.size(14.dp)
                    )
                }
            )
            LocalizedButton(
                onClick = onDelete,
                text = if (deleteConfirm) "确认删除" else "删除",
                appearance = ButtonAppearance.Subtle,
                intent = ButtonIntent.Destructive,
                leadingIcon = { Icon(Icons.Outlined.Delete, null, modifier = Modifier.size(14.dp)) }
            )
        }
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun ScheduleDialog(controller: AppController, onClose: () -> Unit) {
    val catalog = controller.schedules
    var name by remember { mutableStateOf("") }
    var message by remember { mutableStateOf("") }
    var runAt by remember {
        mutableStateOf(
            ZonedDateTime.now().plusHours(1)
                .withSecond(0)
                .withNano(0)
                .format(DateTimeFormatter.ISO_OFFSET_DATE_TIME)
        )
    }
    var interval by remember { mutableStateOf("") }
    var mode by remember { mutableStateOf("src") }
    var model by remember { mutableStateOf("") }
    var projectId by remember { mutableStateOf("") }
    var target by remember { mutableStateOf("") }
    var scope by remember { mutableStateOf("") }

    LocalizedDialogWindow(
        onCloseRequest = onClose,
        title = "新建自动任务",
        state = rememberDialogState(
            size = DpSize(760.dp, 760.dp),
            position = WindowPosition.Aligned(Alignment.Center)
        ),
        resizable = false
    ) {
        SaltTheme(configs = SaltConfigs.default(isDarkTheme = controller.darkTheme)) {
            Column(
                Modifier.fillMaxSize().background(SaltTheme.colors.background).padding(22.dp),
                verticalArrangement = Arrangement.spacedBy(11.dp)
            ) {
                LocalizedText("新建独立自动任务", style = SaltTheme.textStyles.largeTitle)
                ScheduleField("名称") { SpiritTextField(name, { name = it }, "例如：每周资产巡检") }
                ScheduleField("任务消息") {
                    SpiritTextField(message, { message = it }, "说明目标、范围和期望结果", singleLine = false)
                }
                ScheduleField("下次执行时间（ISO 8601，含时区）") {
                    SpiritTextField(runAt, { runAt = it }, "2026-11-26T20:00:00+08:00")
                }
                ScheduleField("重复间隔（秒，留空为单次）") {
                    SpiritTextField(interval, { interval = it }, "例如 86400")
                }
                ScheduleField("模式") {
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        listOf("src", "ctf", "competition").forEach { value ->
                            LocalizedButton(
                                onClick = { mode = value },
                                text = value,
                                appearance = if (mode == value) ButtonAppearance.Filled else ButtonAppearance.Subtle
                            )
                        }
                    }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Box(Modifier.weight(1f)) {
                        ScheduleField("模型") { SpiritTextField(model, { model = it }, "留空使用自动路由") }
                    }
                    Box(Modifier.weight(1f)) {
                        ScheduleField("项目 ID") { SpiritTextField(projectId, { projectId = it }, "可留空") }
                    }
                }
                ScheduleField("目标") { SpiritTextField(target, { target = it }, "域名、URL 或题目标识") }
                ScheduleField("授权范围（每行一个）") {
                    SpiritTextField(scope, { scope = it }, "example.com", singleLine = false)
                }
                catalog.error?.let {
                    LocalizedText(it, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.error)
                }
                Spacer(Modifier.weight(1f))
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                    LocalizedButton(onClick = onClose, text = "取消", appearance = ButtonAppearance.Subtle)
                    Spacer(Modifier.width(8.dp))
                    LocalizedButton(
                        onClick = {
                            catalog.create(
                                name,
                                message,
                                runAt,
                                interval,
                                mode,
                                model,
                                projectId,
                                target,
                                scope
                            )
                            onClose()
                        },
                        text = "创建自动任务",
                        enabled = !catalog.saving
                    )
                }
            }
        }
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun ScheduleMetric(label: String, value: String) {
    Row(
        modifier = Modifier
            .clip(RoundedCornerShape(8.dp))
            .background(SaltTheme.colors.background.copy(alpha = 0.5f))
            .padding(horizontal = 10.dp, vertical = 7.dp),
        horizontalArrangement = Arrangement.spacedBy(6.dp)
    ) {
        LocalizedText(label, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
        LocalizedText(value, style = SaltTheme.textStyles.sub, fontWeight = FontWeight.SemiBold)
    }
}

@Composable
private fun ScheduleField(label: String, content: @Composable () -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        LocalizedText(label, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
        content()
    }
}

private fun formatScheduleTime(value: Double): String {
    if (value <= 0) return "—"
    return runCatching {
        java.time.Instant.ofEpochSecond(value.toLong())
            .atZone(java.time.ZoneId.systemDefault())
            .format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss"))
    }.getOrDefault(value.toString())
}

@Composable
private fun scheduleStateColor(state: String) = when (state) {
    "error" -> SaltTheme.colors.error
    "waiting", "dispatching" -> SaltTheme.colors.warning
    "ready" -> SaltTheme.colors.success
    else -> SaltTheme.colors.subText
}
