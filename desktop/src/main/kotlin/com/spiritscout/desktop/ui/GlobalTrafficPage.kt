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
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
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
import androidx.compose.ui.unit.dp
import com.moriafly.salt.ui.Button
import com.moriafly.salt.ui.ButtonAppearance
import com.moriafly.salt.ui.Card
import com.moriafly.salt.ui.Icon
import com.moriafly.salt.ui.SaltTheme
import com.moriafly.salt.ui.Text
import com.moriafly.salt.ui.UnstableSaltUiApi
import com.spiritscout.desktop.AppController
import com.spiritscout.desktop.model.array
import com.spiritscout.desktop.model.int
import com.spiritscout.desktop.model.long
import com.spiritscout.desktop.model.objectOrEmpty
import com.spiritscout.desktop.model.string

private data class TrafficCatalogProject(
    val id: String,
    val name: String,
    val sessionCount: Int,
    val total: Int
)

private data class TrafficCatalogSession(
    val id: String,
    val title: String,
    val projectId: String,
    val status: String,
    val total: Int,
    val errors: Int,
    val responseBytes: Long
)

@OptIn(UnstableSaltUiApi::class)
@Composable
fun GlobalTrafficPage(controller: AppController) {
    val traffic = controller.traffic
    var selectedProject by remember { mutableStateOf("*") }
    var selectedSession by remember { mutableStateOf("") }
    LaunchedEffect(Unit) { traffic.loadCatalog() }

    val catalog = traffic.catalogJson?.objectOrEmpty()
    val projects = catalog?.array("projects").orEmpty().map { raw ->
        val item = raw.objectOrEmpty()
        TrafficCatalogProject(
            id = item.string("project_id"),
            name = item.string("name"),
            sessionCount = item.int("session_count"),
            total = item.int("total")
        )
    }
    val sessions = catalog?.array("sessions").orEmpty().map { raw ->
        val item = raw.objectOrEmpty()
        TrafficCatalogSession(
            id = item.string("session_id"),
            title = item.string("title"),
            projectId = item.string("project_id"),
            status = item.string("status"),
            total = item.int("total"),
            errors = item.int("errors"),
            responseBytes = item.long("response_bytes")
        )
    }.filter { selectedProject == "*" || it.projectId == selectedProject }

    Row(Modifier.fillMaxSize().padding(20.dp), horizontalArrangement = Arrangement.spacedBy(14.dp)) {
        Card(Modifier.width(390.dp).fillMaxHeight(), color = SaltTheme.colors.subBackground) {
            Column(Modifier.fillMaxSize()) {
                Row(
                    modifier = Modifier.fillMaxWidth().padding(14.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Column(Modifier.weight(1f)) {
                        LocalizedText("全局流量", fontWeight = FontWeight.SemiBold)
                        LocalizedText(
                            "按项目与会话查看",
                            style = SaltTheme.textStyles.sub,
                            color = SaltTheme.colors.subText
                        )
                    }
                    LocalizedButton(
                        onClick = traffic::loadCatalog,
                        text = "刷新",
                        appearance = ButtonAppearance.Subtle,
                        leadingIcon = { Icon(Icons.Outlined.Refresh, null, modifier = Modifier.size(15.dp)) }
                    )
                }
                LazyRow(
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 14.dp),
                    horizontalArrangement = Arrangement.spacedBy(6.dp)
                ) {
                    items(projects, key = { "project:${it.id}" }) { project ->
                        LocalizedButton(
                            onClick = {
                                selectedProject = project.id
                                selectedSession = ""
                            },
                            text = "${project.name} · ${project.total}",
                            appearance = if (selectedProject == project.id) {
                                ButtonAppearance.Filled
                            } else {
                                ButtonAppearance.Subtle
                            }
                        )
                    }
                }
                Box(Modifier.fillMaxWidth().height(1.dp).background(SaltTheme.colors.stroke))
                if (sessions.isEmpty()) {
                    EmptyState("暂无会话流量", "选择其他项目，或先运行会产生网络交互的任务。")
                } else {
                    LazyColumn(
                        modifier = Modifier.fillMaxSize(),
                        contentPadding = androidx.compose.foundation.layout.PaddingValues(12.dp),
                        verticalArrangement = Arrangement.spacedBy(7.dp)
                    ) {
                        items(sessions, key = { it.id }) { session ->
                            Column(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clip(RoundedCornerShape(8.dp))
                                    .background(
                                        if (selectedSession == session.id) {
                                            SaltTheme.colors.highlight.copy(alpha = 0.11f)
                                        } else {
                                            SaltTheme.colors.background.copy(alpha = 0.5f)
                                        }
                                    )
                                    .clickable {
                                        selectedSession = session.id
                                        traffic.openSession(session.id)
                                    }
                                    .padding(11.dp),
                                verticalArrangement = Arrangement.spacedBy(3.dp)
                            ) {
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    LocalizedText(
                                        session.title.ifBlank { session.id },
                                        modifier = Modifier.weight(1f),
                                        fontWeight = FontWeight.Medium,
                                        maxLines = 2
                                    )
                                    StatusPill(session.status, SaltTheme.colors.highlight)
                                }
                                LocalizedText(
                                    "${session.total} 条交互 · ${session.errors} 个失败 · " +
                                        "${formatTrafficBytes(session.responseBytes)} 响应体",
                                    style = SaltTheme.textStyles.sub,
                                    color = SaltTheme.colors.subText
                                )
                            }
                        }
                    }
                }
            }
        }
        Card(Modifier.weight(1f).fillMaxHeight(), color = SaltTheme.colors.subBackground) {
            if (selectedSession.isBlank()) {
                EmptyState("选择会话", "查看 HTTP/WS 交互、原始请求响应、PCAP 和数据包。")
            } else {
                TrafficWorkspacePage(controller)
            }
        }
    }
}

private fun formatTrafficBytes(value: Long): String = when {
    value < 1024 -> "$value B"
    value < 1024 * 1024 -> String.format("%.1f KiB", value / 1024.0)
    else -> String.format("%.1f MiB", value / 1048576.0)
}
