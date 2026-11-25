package com.spiritscout.desktop.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Delete
import androidx.compose.runtime.Composable
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
import com.moriafly.salt.ui.Icon
import com.moriafly.salt.ui.SaltConfigs
import com.moriafly.salt.ui.SaltTheme
import com.moriafly.salt.ui.Text
import com.moriafly.salt.ui.UnstableSaltUiApi
import com.spiritscout.desktop.AppController

@OptIn(UnstableSaltUiApi::class)
@Composable
fun SessionManageWindow(
    controller: AppController,
    mode: String,
    onClose: () -> Unit
) {
    val session = controller.selectedSession
    var title by remember(session?.id, mode) { mutableStateOf(session?.title.orEmpty()) }
    var projectId by remember(session?.id, mode) { mutableStateOf(session?.projectId.orEmpty()) }
    val titleText = when (mode) {
        "rename" -> "重命名会话"
        "project" -> "移动会话到项目"
        else -> "删除会话"
    }

    LocalizedDialogWindow(
        onCloseRequest = onClose,
        title = titleText,
        state = rememberDialogState(
            size = DpSize(620.dp, if (mode == "project") 560.dp else 380.dp),
            position = WindowPosition.Aligned(Alignment.Center)
        ),
        resizable = false
    ) {
        SaltTheme(configs = SaltConfigs.default(isDarkTheme = controller.darkTheme)) {
            Column(
                Modifier.fillMaxSize().background(SaltTheme.colors.background).padding(22.dp),
                verticalArrangement = Arrangement.spacedBy(13.dp)
            ) {
                LocalizedText(titleText, style = SaltTheme.textStyles.largeTitle)
                LocalizedText(
                    when (mode) {
                        "rename" -> "清空标题会恢复自动命名。"
                        "project" -> "移动只改变后续记录的项目归属；历史记忆和当前授权范围保持不变。"
                        else -> "删除会移除会话记录、工作区和交付文件，无法撤销。"
                    },
                    style = SaltTheme.textStyles.sub,
                    color = if (mode == "delete") SaltTheme.colors.error else SaltTheme.colors.subText
                )
                when (mode) {
                    "rename" -> {
                        Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            LocalizedText("会话标题", style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
                            SpiritTextField(title, { title = it }, "留空恢复自动命名")
                        }
                    }
                    "project" -> {
                        LazyColumn(
                            modifier = Modifier.fillMaxWidth().weight(1f),
                            verticalArrangement = Arrangement.spacedBy(7.dp)
                        ) {
                            item {
                                Row(
                                    modifier = Modifier.fillMaxWidth()
                                        .clip(RoundedCornerShape(8.dp))
                                        .background(SaltTheme.colors.subBackground)
                                        .clickable { projectId = "" }
                                        .padding(11.dp),
                                    verticalAlignment = Alignment.CenterVertically
                                ) {
                                    LocalizedText("未分类", modifier = Modifier.weight(1f))
                                    if (projectId.isBlank()) {
                                        StatusPill("当前选择", SaltTheme.colors.highlight)
                                    }
                                }
                            }
                            items(controller.taskProjects, key = { it.id }) { project ->
                                Row(
                                    modifier = Modifier.fillMaxWidth()
                                        .clip(RoundedCornerShape(8.dp))
                                        .background(SaltTheme.colors.subBackground)
                                        .clickable { projectId = project.id }
                                        .padding(11.dp),
                                    verticalAlignment = Alignment.CenterVertically
                                ) {
                                    Column(Modifier.weight(1f)) {
                                        LocalizedText(project.label, fontWeight = FontWeight.Medium)
                                        if (project.detail.isNotBlank()) {
                                            LocalizedText(
                                                project.detail,
                                                style = SaltTheme.textStyles.sub,
                                                color = SaltTheme.colors.subText
                                            )
                                        }
                                    }
                                    if (projectId == project.id) {
                                        StatusPill("当前选择", SaltTheme.colors.highlight)
                                    }
                                }
                            }
                        }
                    }
                    else -> {
                        LocalizedText(session?.title.orEmpty(), fontWeight = FontWeight.SemiBold)
                        LocalizedText(session?.target.orEmpty(), style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
                    }
                }
                Spacer(Modifier.weight(1f))
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                    LocalizedButton(onClick = onClose, text = "取消", appearance = ButtonAppearance.Subtle)
                    Spacer(Modifier.width(8.dp))
                    if (mode == "delete") {
                        LocalizedButton(
                            onClick = { controller.deleteSelectedSession(onClose) },
                            text = "确认删除",
                            appearance = ButtonAppearance.Subtle,
                            intent = ButtonIntent.Destructive,
                            leadingIcon = { Icon(Icons.Outlined.Delete, null) }
                        )
                    } else {
                        LocalizedButton(
                            onClick = {
                                if (mode == "rename") {
                                    controller.renameSelectedSession(title, onClose)
                                } else {
                                    controller.moveSelectedSession(projectId, onClose)
                                }
                            },
                            text = if (mode == "rename") "保存标题" else "移动会话"
                        )
                    }
                }
            }
        }
    }
}
