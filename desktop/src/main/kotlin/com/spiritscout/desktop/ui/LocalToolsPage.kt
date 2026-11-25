package com.spiritscout.desktop.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Delete
import androidx.compose.material.icons.outlined.FolderOpen
import androidx.compose.material.icons.outlined.Refresh
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
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
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
import com.spiritscout.desktop.state.LocalToolItem
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import javax.swing.JFileChooser

@OptIn(UnstableSaltUiApi::class)
@Composable
fun LocalToolsPage(controller: AppController) {
    val library = controller.localTools
    var enabled by remember(library.config) { mutableStateOf(library.config.enabled) }
    var dirs by remember(library.config) { mutableStateOf(library.config.dirs) }
    var timeout by remember(library.config) { mutableStateOf(library.config.timeoutSeconds.toString()) }
    var depth by remember(library.config) { mutableStateOf(library.config.maxDepth.toString()) }
    var maxFiles by remember(library.config) { mutableStateOf(library.config.maxFiles.toString()) }
    var maxStage by remember(library.config) { mutableStateOf(library.config.maxStageMb.toString()) }
    var query by remember { mutableStateOf("") }
    LaunchedEffect(Unit) { library.refresh() }

    val visible = library.tools.filter {
        query.isBlank() || listOf(it.name, it.path, it.dir).any { value ->
            value.contains(query, ignoreCase = true)
        }
    }

    Column(
        modifier = Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                LocalizedText("本地工具", style = SaltTheme.textStyles.largeTitle)
                LocalizedText(
                    "把本机 exe 和脚本编入索引，Agent 通过 local_tool 检索运行；运行使用暂存副本并在结束后核对还原。",
                    style = SaltTheme.textStyles.sub,
                    color = SaltTheme.colors.subText
                )
            }
            LocalizedButton(
                onClick = library::rescan,
                text = "重新扫描",
                appearance = ButtonAppearance.Subtle,
                enabled = !library.saving,
                leadingIcon = { Icon(Icons.Outlined.Refresh, null, modifier = Modifier.size(15.dp)) }
            )
            Spacer(Modifier.width(8.dp))
            LocalizedButton(
                onClick = library::cleanup,
                text = "清理暂存",
                appearance = ButtonAppearance.Subtle,
                intent = ButtonIntent.Destructive,
                enabled = !library.saving
            )
        }
        library.error?.let { ErrorBlock(it) }
        if (library.message.isNotBlank()) {
            LocalizedText(library.message, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.success)
        }
        Card(Modifier.fillMaxWidth(), color = SaltTheme.colors.subBackground) {
            Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        LocalizedText("允许 Agent 使用本地工具", fontWeight = FontWeight.SemiBold)
                        LocalizedText(
                            "关闭后 Agent 会明确收到不可用状态。",
                            style = SaltTheme.textStyles.sub,
                            color = SaltTheme.colors.subText
                        )
                    }
                    Switcher(state = enabled, onChange = { enabled = it })
                }
                LocalizedText("工具目录", style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
                LazyRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    items(dirs) { dir ->
                        Row(
                            modifier = Modifier
                                .clip(RoundedCornerShape(8.dp))
                                .background(SaltTheme.colors.background.copy(alpha = 0.55f))
                                .padding(start = 10.dp, end = 5.dp, top = 6.dp, bottom = 6.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(5.dp)
                        ) {
                            LocalizedText(dir, style = SaltTheme.textStyles.sub, fontFamily = FontFamily.Monospace)
                            LocalizedButton(
                                onClick = { dirs = dirs - dir },
                                text = "移除",
                                appearance = ButtonAppearance.Subtle
                            )
                        }
                    }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                    LocalizedButton(
                        onClick = {
                            val chooser = JFileChooser().apply {
                                fileSelectionMode = JFileChooser.DIRECTORIES_ONLY
                                dialogTitle = "选择本地工具目录"
                            }
                            if (chooser.showOpenDialog(null) == JFileChooser.APPROVE_OPTION) {
                                val path = chooser.selectedFile?.absolutePath
                                if (path != null && path !in dirs) dirs = dirs + path
                            }
                        },
                        text = "选择文件夹",
                        appearance = ButtonAppearance.Subtle,
                        leadingIcon = { Icon(Icons.Outlined.FolderOpen, null, modifier = Modifier.size(15.dp)) }
                    )
                    LocalizedButton(
                        onClick = {
                            library.save(enabled, dirs, timeout, depth, maxFiles, maxStage)
                        },
                        text = if (library.saving) "正在扫描…" else "保存并扫描",
                        enabled = !library.saving
                    )
                    LocalizedText(
                        "索引 ${library.indexed} 个工具 · ${formatScannedAt(library.scannedAt)}",
                        style = SaltTheme.textStyles.sub,
                        color = SaltTheme.colors.subText
                    )
                }
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    LocalToolField("超时秒数", timeout, { timeout = it })
                    LocalToolField("最大深度", depth, { depth = it })
                    LocalToolField("最大文件数", maxFiles, { maxFiles = it })
                    LocalToolField("暂存上限 MB", maxStage, { maxStage = it })
                }
            }
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            LocalizedText("索引结果", modifier = Modifier.weight(1f), fontWeight = FontWeight.SemiBold)
            Box(Modifier.width(360.dp)) {
                SpiritTextField(query, { query = it }, "按名称或路径过滤")
            }
        }
        if (visible.isEmpty()) {
            EmptyState(
                if (dirs.isEmpty()) "还没有工具目录" else "没有匹配的本地工具",
                if (dirs.isEmpty()) "选择一个不含盘符根的绝对目录，然后保存并扫描。" else "可调整搜索词或重新扫描。"
            )
        } else {
            LazyColumn(
                modifier = Modifier.fillMaxWidth().height(480.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp)
            ) {
                items(visible, key = { it.path }) { tool -> LocalToolRow(tool) }
            }
        }
        LocalizedText(
            library.notice.ifBlank {
                "运行目录：${library.runsDir.ifBlank { "工作区 local-tools/runs" }}。正常运行结束即销毁副本。"
            },
            style = SaltTheme.textStyles.sub,
            color = SaltTheme.colors.subText
        )
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun LocalToolField(label: String, value: String, onChange: (String) -> Unit) {
    Column(modifier = Modifier.width(150.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
        LocalizedText(label, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
        SpiritTextField(value, onChange, "—")
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun LocalToolRow(tool: LocalToolItem) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(SaltTheme.colors.subBackground)
            .padding(12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        Box(
            modifier = Modifier.size(32.dp).clip(RoundedCornerShape(8.dp))
                .background(SaltTheme.colors.highlight.copy(alpha = 0.12f)),
            contentAlignment = Alignment.Center
        ) {
            Icon(Icons.Outlined.Terminal, null, modifier = Modifier.size(16.dp), tint = SaltTheme.colors.highlight)
        }
        Column(Modifier.weight(1f)) {
            LocalizedText(tool.name, fontWeight = FontWeight.Medium)
            LocalizedText(
                tool.file.ifBlank { tool.path },
                style = SaltTheme.textStyles.sub,
                color = SaltTheme.colors.subText,
                fontFamily = FontFamily.Monospace
            )
        }
        StatusPill(tool.ext.ifBlank { "工具" }, SaltTheme.colors.highlight)
        LocalizedText(formatToolSize(tool.size), style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
        LocalizedText(tool.dir, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText, fontFamily = FontFamily.Monospace)
    }
}

private fun formatScannedAt(value: Double): String {
    if (value <= 0) return "尚未扫描"
    return runCatching {
        Instant.ofEpochSecond(value.toLong())
            .atZone(ZoneId.systemDefault())
            .format(DateTimeFormatter.ofPattern("MM-dd HH:mm:ss"))
    }.getOrDefault("尚未扫描")
}

private fun formatToolSize(value: Long): String = when {
    value >= 1024 * 1024 -> String.format("%.1f MB", value / 1048576.0)
    value >= 1024 -> "${value / 1024} KB"
    else -> "$value B"
}
