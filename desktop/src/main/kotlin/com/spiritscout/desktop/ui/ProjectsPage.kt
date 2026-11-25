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
import androidx.compose.material.icons.outlined.Delete
import androidx.compose.material.icons.outlined.Edit
import androidx.compose.material.icons.outlined.Folder
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
import com.spiritscout.desktop.model.Section
import com.spiritscout.desktop.model.array
import com.spiritscout.desktop.model.objectOrEmpty
import com.spiritscout.desktop.model.string
import com.spiritscout.desktop.state.ProjectRow

@OptIn(UnstableSaltUiApi::class)
@Composable
fun ProjectsPage(controller: AppController) {
    val catalog = controller.projectCatalog
    var adding by remember { mutableStateOf(false) }
    var editing by remember { mutableStateOf<ProjectRow?>(null) }
    var selected by remember { mutableStateOf("") }
    var deleteConfirm by remember { mutableStateOf("") }
    LaunchedEffect(Unit) { catalog.refresh() }
    LaunchedEffect(catalog.projects.map { it.id }) {
        if (catalog.projects.none { it.id == selected }) selected = catalog.projects.firstOrNull()?.id.orEmpty()
    }
    LaunchedEffect(selected) {
        if (selected.isNotBlank()) catalog.loadDetails(selected)
    }

    Column(Modifier.fillMaxSize().padding(24.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                LocalizedText("项目", style = SaltTheme.textStyles.largeTitle)
                LocalizedText(
                    "项目是共享记忆分区，不是授权边界。删除项目只解绑，资产、发现和历史记录会转为未分类。",
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
                onClick = { adding = true },
                text = "新建项目",
                leadingIcon = { Icon(Icons.Outlined.Add, null, modifier = Modifier.size(15.dp)) }
            )
        }
        catalog.error?.let { ErrorBlock(it) }
        if (catalog.message.isNotBlank()) {
            LocalizedText(catalog.message, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.success)
        }
        Row(Modifier.fillMaxSize(), horizontalArrangement = Arrangement.spacedBy(14.dp)) {
            Card(Modifier.width(480.dp).fillMaxHeight(), color = SaltTheme.colors.subBackground) {
                Column(Modifier.fillMaxSize()) {
                    Row(Modifier.fillMaxWidth().padding(15.dp), verticalAlignment = Alignment.CenterVertically) {
                        LocalizedText(
                            "${catalog.projects.size} 个项目",
                            modifier = Modifier.weight(1f),
                            fontWeight = FontWeight.SemiBold
                        )
                        if (catalog.loading) {
                            LocalizedText("同步中…", style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
                        }
                    }
                    Box(Modifier.fillMaxWidth().height(1.dp).background(SaltTheme.colors.stroke))
                    if (catalog.projects.isEmpty()) {
                        EmptyState("暂无项目", "新建项目后按业务域组织会话、资产和漏洞。")
                    } else {
                        LazyColumn(
                            modifier = Modifier.fillMaxSize(),
                            contentPadding = androidx.compose.foundation.layout.PaddingValues(12.dp),
                            verticalArrangement = Arrangement.spacedBy(8.dp)
                        ) {
                            items(catalog.projects, key = { it.id }) { project ->
                                ProjectRow(
                                    project = project,
                                    selected = selected == project.id,
                                    onClick = { selected = project.id }
                                )
                            }
                        }
                    }
                }
            }
            Card(Modifier.weight(1f).fillMaxHeight(), color = SaltTheme.colors.subBackground) {
                val project = catalog.projects.firstOrNull { it.id == selected }
                if (project == null) {
                    EmptyState("选择一个项目", "查看项目概览并进入相关资产收集。")
                } else {
                    Column(Modifier.fillMaxSize().padding(20.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Box(
                                Modifier.size(46.dp).clip(RoundedCornerShape(10.dp))
                                    .background(SaltTheme.colors.highlight.copy(alpha = 0.12f)),
                                contentAlignment = Alignment.Center
                            ) {
                                Icon(
                                    Icons.Outlined.Folder,
                                    null,
                                    modifier = Modifier.size(22.dp),
                                    tint = SaltTheme.colors.highlight
                                )
                            }
                            Spacer(Modifier.width(12.dp))
                            Column(Modifier.weight(1f)) {
                                LocalizedText(project.name, style = SaltTheme.textStyles.largeTitle)
                                LocalizedText(project.id, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
                            }
                            LocalizedButton(
                                onClick = { editing = project },
                                text = "编辑",
                                appearance = ButtonAppearance.Subtle,
                                leadingIcon = { Icon(Icons.Outlined.Edit, null, modifier = Modifier.size(15.dp)) }
                            )
                            Spacer(Modifier.width(7.dp))
                            LocalizedButton(
                                onClick = {
                                    if (deleteConfirm == project.id) {
                                        catalog.delete(project.id)
                                        deleteConfirm = ""
                                    } else {
                                        deleteConfirm = project.id
                                    }
                                },
                                text = if (deleteConfirm == project.id) "确认删除" else "删除",
                                appearance = ButtonAppearance.Subtle,
                                intent = ButtonIntent.Destructive,
                                leadingIcon = { Icon(Icons.Outlined.Delete, null, modifier = Modifier.size(15.dp)) }
                            )
                        }
                        LocalizedText(
                            project.description.ifBlank { "暂无项目说明。" },
                            style = SaltTheme.textStyles.paragraph,
                            color = SaltTheme.colors.subText
                        )
                        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                            ProjectMetric("会话", project.sessionCount.toString())
                            ProjectMetric("资产", project.assetCount.toString())
                            ProjectMetric("发现", project.findingCount.toString())
                        }
                        val projectSessions = controller.sessions.filter { it.projectId == project.id }.take(6)
                        val projectTargets = catalog.projectTargets?.objectOrEmpty()
                            ?.array("targets")
                            .orEmpty()
                            .take(8)
                        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                                LocalizedText("关联会话", fontWeight = FontWeight.SemiBold)
                                if (projectSessions.isEmpty()) {
                                    LocalizedText(
                                        "暂无会话。",
                                        style = SaltTheme.textStyles.sub,
                                        color = SaltTheme.colors.subText
                                    )
                                } else {
                                    projectSessions.forEach { session ->
                                        Row(
                                            modifier = Modifier.fillMaxWidth()
                                                .clickable { controller.openSession(session) }
                                                .padding(vertical = 4.dp),
                                            verticalAlignment = Alignment.CenterVertically
                                        ) {
                                            LocalizedText(
                                                session.title,
                                                modifier = Modifier.weight(1f),
                                                style = SaltTheme.textStyles.sub,
                                                maxLines = 1
                                            )
                                            StatusPill(session.stateLabel, SaltTheme.colors.highlight)
                                        }
                                    }
                                }
                            }
                            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                                LocalizedText("项目资产", fontWeight = FontWeight.SemiBold)
                                if (projectTargets.isEmpty()) {
                                    LocalizedText(
                                        if (catalog.detailLoading) "正在读取…" else "暂无资产。",
                                        style = SaltTheme.textStyles.sub,
                                        color = SaltTheme.colors.subText
                                    )
                                } else {
                                    projectTargets.forEach { raw ->
                                        val asset = raw.objectOrEmpty()
                                        LocalizedText(
                                            asset.string("value"),
                                            style = SaltTheme.textStyles.sub,
                                            color = SaltTheme.colors.subText,
                                            maxLines = 1
                                        )
                                    }
                                }
                            }
                        }
                        Box(Modifier.fillMaxWidth().height(1.dp).background(SaltTheme.colors.stroke))
                        LocalizedText("关联操作", fontWeight = FontWeight.SemiBold)
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            LocalizedButton(
                                onClick = {
                                    controller.assetCollection.selectProject(project.id)
                                    controller.navigate(Section.ASSETS)
                                },
                                text = "进入资产收集",
                                appearance = ButtonAppearance.Subtle
                            )
                            LocalizedButton(
                                onClick = {
                                    controller.navigate(Section.TASKS)
                                },
                                text = "查看会话",
                                appearance = ButtonAppearance.Subtle
                            )
                        }
                        LocalizedText(
                            "项目归属不改变任务授权；历史资产和候选仍需重新确认范围和验证状态。",
                            style = SaltTheme.textStyles.sub,
                            color = SaltTheme.colors.subText
                        )
                    }
                }
            }
        }
    }

    if (adding || editing != null) {
        ProjectDialog(controller, editing) {
            adding = false
            editing = null
        }
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun ProjectRow(project: ProjectRow, selected: Boolean, onClick: () -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(
                if (selected) SaltTheme.colors.highlight.copy(alpha = 0.11f)
                else SaltTheme.colors.background.copy(alpha = 0.5f)
            )
            .clickable(onClick = onClick)
            .padding(13.dp),
        verticalArrangement = Arrangement.spacedBy(4.dp)
    ) {
        LocalizedText(project.name, fontWeight = FontWeight.SemiBold)
        LocalizedText(
            project.description.ifBlank { "暂无说明" },
            style = SaltTheme.textStyles.sub,
            color = SaltTheme.colors.subText,
            maxLines = 2
        )
        LocalizedText(
            "${project.sessionCount} 会话 · ${project.assetCount} 资产 · ${project.findingCount} 发现",
            style = SaltTheme.textStyles.sub,
            color = SaltTheme.colors.subText
        )
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun ProjectMetric(label: String, value: String) {
    Row(
        modifier = Modifier
            .clip(RoundedCornerShape(8.dp))
            .background(SaltTheme.colors.background.copy(alpha = 0.5f))
            .padding(horizontal = 12.dp, vertical = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(7.dp)
    ) {
        LocalizedText(label, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
        LocalizedText(value, style = SaltTheme.textStyles.sub, fontWeight = FontWeight.SemiBold)
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun ProjectDialog(
    controller: AppController,
    project: ProjectRow?,
    onClose: () -> Unit
) {
    var name by remember(project?.id) { mutableStateOf(project?.name.orEmpty()) }
    var description by remember(project?.id) { mutableStateOf(project?.description.orEmpty()) }
    LocalizedDialogWindow(
        onCloseRequest = onClose,
        title = if (project == null) "新建项目" else "编辑项目",
        state = rememberDialogState(
            size = DpSize(620.dp, 520.dp),
            position = WindowPosition.Aligned(Alignment.Center)
        ),
        resizable = false
    ) {
        SaltTheme(configs = SaltConfigs.default(isDarkTheme = controller.darkTheme)) {
            Column(
                Modifier.fillMaxSize().background(SaltTheme.colors.background).padding(22.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                LocalizedText(
                    if (project == null) "新建项目" else "编辑 ${project.name}",
                    style = SaltTheme.textStyles.largeTitle
                )
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    LocalizedText("项目名称", style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
                    SpiritTextField(name, { name = it }, "业务域或客户名称")
                }
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    LocalizedText("项目说明", style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
                    SpiritTextField(description, { description = it }, "规则、背景和协作说明", singleLine = false)
                }
                controller.projectCatalog.error?.let {
                    LocalizedText(it, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.error)
                }
                Spacer(Modifier.weight(1f))
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                    LocalizedButton(onClick = onClose, text = "取消", appearance = ButtonAppearance.Subtle)
                    Spacer(Modifier.width(8.dp))
                    LocalizedButton(
                        onClick = {
                            controller.projectCatalog.save(project?.id, name, description)
                            onClose()
                        },
                        text = "保存项目",
                        enabled = !controller.projectCatalog.saving
                    )
                }
            }
        }
    }
}
