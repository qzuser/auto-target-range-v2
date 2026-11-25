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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Delete
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
import com.moriafly.salt.ui.Icon
import com.moriafly.salt.ui.SaltConfigs
import com.moriafly.salt.ui.SaltTheme
import com.moriafly.salt.ui.Switcher
import com.moriafly.salt.ui.Text
import com.moriafly.salt.ui.UnstableSaltUiApi
import com.spiritscout.desktop.AppController
import com.spiritscout.desktop.model.array
import com.spiritscout.desktop.model.boolean
import com.spiritscout.desktop.model.element
import com.spiritscout.desktop.model.objectOrEmpty
import com.spiritscout.desktop.model.string

@OptIn(UnstableSaltUiApi::class)
@Composable
fun StorageCleanupWindow(controller: AppController, onClose: () -> Unit) {
    var selectedId by remember { mutableStateOf("") }
    var database by remember { mutableStateOf(true) }
    var caches by remember { mutableStateOf(true) }
    LaunchedEffect(Unit) {
        controller.loadStorageOverview()
    }
    LaunchedEffect(selectedId) {
        if (selectedId.isNotBlank()) controller.loadStoragePreview(selectedId)
    }

    LocalizedDialogWindow(
        onCloseRequest = onClose,
        title = "存储清理",
        state = rememberDialogState(
            size = DpSize(920.dp, 720.dp),
            position = WindowPosition.Aligned(Alignment.Center)
        ),
        resizable = true
    ) {
        SaltTheme(configs = SaltConfigs.default(isDarkTheme = controller.darkTheme)) {
            Row(
                modifier = Modifier.fillMaxSize().background(SaltTheme.colors.background).padding(20.dp),
                horizontalArrangement = Arrangement.spacedBy(14.dp)
            ) {
                val sessions = controller.storageJson.orEmptyStorageSessions()
                Column(
                    modifier = Modifier.width(390.dp).fillMaxHeight()
                        .clip(RoundedCornerShape(8.dp))
                        .background(SaltTheme.colors.subBackground)
                ) {
                    LocalizedText(
                        "选择会话",
                        modifier = Modifier.padding(14.dp),
                        fontWeight = FontWeight.SemiBold
                    )
                    Box(Modifier.fillMaxWidth().background(SaltTheme.colors.stroke).padding(top = 1.dp))
                    if (sessions.isEmpty()) {
                        EmptyState("暂无会话", "加载存储概览后可选择会话。")
                    } else {
                        LazyColumn(
                            modifier = Modifier.fillMaxSize(),
                            contentPadding = androidx.compose.foundation.layout.PaddingValues(10.dp),
                            verticalArrangement = Arrangement.spacedBy(6.dp)
                        ) {
                            items(sessions, key = { it.id }) { session ->
                                Column(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .clip(RoundedCornerShape(7.dp))
                                        .background(
                                            if (selectedId == session.id) {
                                                SaltTheme.colors.highlight.copy(alpha = 0.1f)
                                            } else {
                                                SaltTheme.colors.background.copy(alpha = 0.5f)
                                            }
                                        )
                                        .clickable { selectedId = session.id }
                                        .padding(10.dp),
                                    verticalArrangement = Arrangement.spacedBy(3.dp)
                                ) {
                                    LocalizedText(session.title, fontWeight = FontWeight.Medium, maxLines = 2)
                                    LocalizedText(
                                        "${formatStorageBytes(session.bytes)} · ${session.status}",
                                        style = SaltTheme.textStyles.sub,
                                        color = SaltTheme.colors.subText
                                    )
                                    session.blockedReason.takeIf(String::isNotBlank)?.let {
                                        LocalizedText(
                                            it,
                                            style = SaltTheme.textStyles.sub,
                                            color = SaltTheme.colors.warning
                                        )
                                    }
                                }
                            }
                        }
                    }
                }

                Column(
                    modifier = Modifier.weight(1f).fillMaxHeight(),
                    verticalArrangement = Arrangement.spacedBy(12.dp)
                ) {
                    LocalizedText("清理范围", style = SaltTheme.textStyles.largeTitle)
                    LocalizedText(
                        "只清理所选会话的数据库冗余或沙箱包下载缓存；不会删除任务、报告、附件、Flag、浏览器登录态或其他会话。",
                        style = SaltTheme.textStyles.sub,
                        color = SaltTheme.colors.subText
                    )
                    StorageSwitch(
                        title = "精简数据库",
                        description = "压缩历史观测和冗余记录，保留可恢复摘要。",
                        checked = database,
                        onChange = { database = it }
                    )
                    StorageSwitch(
                        title = "清理下载缓存",
                        description = "只清理 pip、uv、npm 下载缓存；后续可能重新下载。",
                        checked = caches,
                        onChange = { caches = it }
                    )
                    val preview = controller.storagePreviewJson?.objectOrEmpty()
                    preview?.let {
                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .weight(1f)
                                .clip(RoundedCornerShape(8.dp))
                                .background(SaltTheme.colors.subBackground)
                                .verticalScroll(rememberScrollState())
                                .padding(14.dp),
                            verticalArrangement = Arrangement.spacedBy(8.dp)
                        ) {
                            LocalizedText("清理预览", fontWeight = FontWeight.SemiBold)
                            listOf(
                                "会话大小" to formatStorageBytes(
                                    it.element("bytes")?.toString()?.toLongOrNull() ?: 0
                                ),
                                "下载缓存" to formatStorageBytes(
                                    it.element("cache_bytes")?.toString()?.toLongOrNull() ?: 0
                                ),
                                "阻塞原因" to it.string("blocked_reason").ifBlank { "无" }
                            ).forEach { (label, value) ->
                                Row(
                                    modifier = Modifier.fillMaxWidth(),
                                    horizontalArrangement = Arrangement.spacedBy(10.dp)
                                ) {
                                    LocalizedText(
                                        label,
                                        modifier = Modifier.width(110.dp),
                                        style = SaltTheme.textStyles.sub,
                                        color = SaltTheme.colors.subText
                                    )
                                    LocalizedText(value, style = SaltTheme.textStyles.sub)
                                }
                            }
                            val db = it.element("database")?.objectOrEmpty()
                            if (db != null && db.isNotEmpty()) {
                                LocalizedText("数据库", fontWeight = FontWeight.Medium)
                                db.forEach { (key, value) ->
                                    LocalizedText(
                                        "$key: ${value.toString().trim('"')}",
                                        style = SaltTheme.textStyles.sub,
                                        color = SaltTheme.colors.subText
                                    )
                                }
                            }
                        }
                    } ?: LocalizedText(
                        if (selectedId.isBlank()) "请选择会话查看预览。" else "正在读取存储预览…",
                        modifier = Modifier.weight(1f),
                        style = SaltTheme.textStyles.sub,
                        color = SaltTheme.colors.subText
                    )
                    val blocked = preview?.string("blocked_reason").orEmpty()
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.End,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        if (blocked.isNotBlank()) {
                            LocalizedText(
                                blocked,
                                modifier = Modifier.weight(1f),
                                style = SaltTheme.textStyles.sub,
                                color = SaltTheme.colors.warning
                            )
                        }
                        LocalizedButton(onClick = onClose, text = "取消", appearance = ButtonAppearance.Subtle)
                        Spacer(Modifier.width(8.dp))
                        LocalizedButton(
                            onClick = {
                                controller.runStorageCleanup(selectedId, database, caches)
                                onClose()
                            },
                            text = "确认清理",
                            enabled = selectedId.isNotBlank() &&
                                blocked.isBlank() &&
                                (database || caches),
                            appearance = ButtonAppearance.Subtle,
                            intent = ButtonIntent.Destructive,
                            leadingIcon = { Icon(Icons.Outlined.Delete, null, modifier = Modifier.size(15.dp)) }
                        )
                    }
                }
            }
        }
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun StorageSwitch(
    title: String,
    description: String,
    checked: Boolean,
    onChange: (Boolean) -> Unit
) {
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        Column(Modifier.weight(1f)) {
            LocalizedText(title, fontWeight = FontWeight.Medium)
            LocalizedText(description, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
        }
        Switcher(state = checked, onChange = onChange)
    }
}

private data class StorageSessionRow(
    val id: String,
    val title: String,
    val status: String,
    val bytes: Long,
    val blockedReason: String
)

private fun kotlinx.serialization.json.JsonElement?.orEmptyStorageSessions(): List<StorageSessionRow> {
    val root = this?.objectOrEmpty() ?: return emptyList()
    return root.array("sessions").mapNotNull { raw ->
        val item = raw.objectOrEmpty()
        val id = item.string("session_id")
        if (id.isBlank()) null else StorageSessionRow(
            id = id,
            title = item.string("title").ifBlank { id },
            status = item.string("status"),
            bytes = item.element("bytes")?.toString()?.toLongOrNull() ?: 0,
            blockedReason = item.string("blocked_reason")
        )
    }
}

private fun formatStorageBytes(value: Long): String = when {
    value < 1024 -> "$value B"
    value < 1024 * 1024 -> String.format("%.1f KiB", value / 1024.0)
    value < 1024L * 1024 * 1024 -> String.format("%.1f MiB", value / 1048576.0)
    else -> String.format("%.2f GiB", value / 1073741824.0)
}
