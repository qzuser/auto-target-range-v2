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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Delete
import androidx.compose.material.icons.outlined.Lightbulb
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.Source
import androidx.compose.material.icons.outlined.Undo
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
import com.moriafly.salt.ui.ButtonIntent
import com.moriafly.salt.ui.Card
import com.moriafly.salt.ui.Icon
import com.moriafly.salt.ui.SaltTheme
import com.moriafly.salt.ui.Text
import com.moriafly.salt.ui.UnstableSaltUiApi
import com.spiritscout.desktop.AppController
import com.spiritscout.desktop.model.ResourceItem
import com.spiritscout.desktop.model.Section
import com.spiritscout.desktop.model.array
import com.spiritscout.desktop.model.element
import com.spiritscout.desktop.model.objectOrEmpty
import com.spiritscout.desktop.model.string
import kotlinx.serialization.json.Json

@OptIn(UnstableSaltUiApi::class)
@Composable
fun ExperiencePage(controller: AppController) {
    var query by remember { mutableStateOf("") }
    var selectedId by remember { mutableStateOf("") }
    var deleteConfirm by remember { mutableStateOf("") }
    val all = controller.resources[Section.EXPERIENCE].orEmpty()
    val filtered = all.filter { item ->
        query.isBlank() || listOf(item.title, item.subtitle, item.meta, item.status)
            .any { it.contains(query, ignoreCase = true) }
    }
    LaunchedEffect(Unit) {
        if (controller.resources[Section.EXPERIENCE] == null) controller.refreshCurrent()
    }
    LaunchedEffect(filtered.map { it.id }) {
        if (filtered.none { it.id == selectedId }) selectedId = filtered.firstOrNull()?.id.orEmpty()
    }
    val selected = filtered.firstOrNull { it.id == selectedId }

    Column(Modifier.fillMaxSize().padding(24.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                LocalizedText("经验提炼", style = SaltTheme.textStyles.largeTitle)
                LocalizedText(
                    "审核模型提炼出的可复用经验，追溯来源会话，合并相似记录或撤销整理。",
                    style = SaltTheme.textStyles.sub,
                    color = SaltTheme.colors.subText
                )
            }
            LocalizedButton(
                onClick = controller::openExperienceMerge,
                text = "整理相似经验",
                appearance = ButtonAppearance.Subtle
            )
            Spacer(Modifier.width(8.dp))
            LocalizedButton(
                onClick = controller::openExperienceTools,
                text = "快照工具",
                appearance = ButtonAppearance.Subtle
            )
            Spacer(Modifier.width(8.dp))
            LocalizedButton(
                onClick = controller::refreshCurrent,
                text = "刷新",
                appearance = ButtonAppearance.Subtle,
                leadingIcon = { Icon(Icons.Outlined.Refresh, null, modifier = Modifier.size(15.dp)) }
            )
        }
        Box(Modifier.width(420.dp)) {
            SpiritTextField(query, { query = it }, "搜索经验、上下文或标签…")
        }
        if (controller.errors[Section.EXPERIENCE] != null) {
            ErrorBlock(controller.errors[Section.EXPERIENCE]!!)
        }
        Row(Modifier.fillMaxSize(), horizontalArrangement = Arrangement.spacedBy(14.dp)) {
            Card(Modifier.width(480.dp).fillMaxHeight(), color = SaltTheme.colors.subBackground) {
                Column(Modifier.fillMaxSize()) {
                    Row(Modifier.fillMaxWidth().padding(15.dp), verticalAlignment = Alignment.CenterVertically) {
                        LocalizedText(
                            "${filtered.size} 条经验",
                            modifier = Modifier.weight(1f),
                            fontWeight = FontWeight.SemiBold
                        )
                        if (controller.loading[Section.EXPERIENCE] == true) {
                            LocalizedText("同步中…", style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
                        }
                    }
                    Box(Modifier.fillMaxWidth().height(1.dp).background(SaltTheme.colors.stroke))
                    if (filtered.isEmpty()) {
                        EmptyState("暂无经验记录", "会话执行后可由 Agent 自动提炼，或在会话页手动提炼。")
                    } else {
                        LazyColumn(
                            modifier = Modifier.fillMaxSize(),
                            contentPadding = androidx.compose.foundation.layout.PaddingValues(12.dp),
                            verticalArrangement = Arrangement.spacedBy(8.dp)
                        ) {
                            items(filtered, key = { it.id }) { item ->
                                ExperienceListRow(
                                    item,
                                    selected = item.id == selectedId,
                                    onClick = { selectedId = item.id }
                                )
                            }
                        }
                    }
                }
            }
            Card(Modifier.weight(1f).fillMaxHeight(), color = SaltTheme.colors.subBackground) {
                if (selected == null) {
                    EmptyState("选择一条经验", "查看提炼内容、来源和质量状态。")
                } else {
                    ExperienceDetail(
                        controller,
                        selected,
                        deleteConfirm == selected.id,
                        onDelete = {
                            if (deleteConfirm == selected.id) {
                                controller.deleteExperience(selected)
                                deleteConfirm = ""
                            } else {
                                deleteConfirm = selected.id
                            }
                        }
                    )
                }
            }
        }
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun ExperienceListRow(item: ResourceItem, selected: Boolean, onClick: () -> Unit) {
    val parsed = remember(item.rawJson) {
        runCatching { Json.parseToJsonElement(item.rawJson).objectOrEmpty() }.getOrNull()
    }
    val tags = parsed?.array("tags").orEmpty().map { it.toString().trim('"') }
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(
                if (selected) SaltTheme.colors.highlight.copy(alpha = 0.11f)
                else SaltTheme.colors.background.copy(alpha = 0.5f)
            )
            .clickable(onClick = onClick)
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(4.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            LocalizedText(item.title, modifier = Modifier.weight(1f), fontWeight = FontWeight.SemiBold, maxLines = 2)
            StatusPill(item.status, SaltTheme.colors.highlight)
        }
        LocalizedText(
            item.subtitle.ifBlank { "暂无上下文" },
            style = SaltTheme.textStyles.sub,
            color = SaltTheme.colors.subText,
            maxLines = 2
        )
        LocalizedText(
            tags.joinToString(" · ").ifBlank { item.meta.ifBlank { "无标签" } },
            style = SaltTheme.textStyles.sub,
            color = SaltTheme.colors.subText
        )
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun ExperienceDetail(
    controller: AppController,
    item: ResourceItem,
    deleteConfirm: Boolean,
    onDelete: () -> Unit
) {
    val parsed = remember(item.rawJson) {
        runCatching { Json.parseToJsonElement(item.rawJson).objectOrEmpty() }.getOrNull()
    }
    val sourceSession = parsed?.string("source_session").orEmpty()
    val merged = parsed?.element("merged_from")?.toString()
        ?.let { it != "null" && it != "[]" } == true
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(
                Modifier.size(42.dp).clip(RoundedCornerShape(9.dp))
                    .background(SaltTheme.colors.highlight.copy(alpha = 0.12f)),
                contentAlignment = Alignment.Center
            ) {
                Icon(Icons.Outlined.Lightbulb, null, tint = SaltTheme.colors.highlight)
            }
            Spacer(Modifier.width(11.dp))
            Column(Modifier.weight(1f)) {
                LocalizedText(item.title, style = SaltTheme.textStyles.largeTitle)
                LocalizedText(item.id, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
            }
            StatusPill(item.status, SaltTheme.colors.highlight)
        }
        LocalizedText(item.subtitle, style = SaltTheme.textStyles.paragraph)
        Row(horizontalArrangement = Arrangement.spacedBy(7.dp)) {
            if (sourceSession.isNotBlank()) {
                LocalizedButton(
                    onClick = { controller.openExperienceSource(item) },
                    text = "打开来源会话",
                    appearance = ButtonAppearance.Subtle,
                    leadingIcon = { Icon(Icons.Outlined.Source, null, modifier = Modifier.size(15.dp)) }
                )
            }
            if (merged) {
                LocalizedButton(
                    onClick = { controller.restoreExperience(item) },
                    text = "撤销整理",
                    appearance = ButtonAppearance.Subtle,
                    leadingIcon = { Icon(Icons.Outlined.Undo, null, modifier = Modifier.size(15.dp)) }
                )
            }
            LocalizedButton(
                onClick = onDelete,
                text = if (deleteConfirm) "确认删除" else "删除经验",
                appearance = ButtonAppearance.Subtle,
                intent = ButtonIntent.Destructive,
                leadingIcon = { Icon(Icons.Outlined.Delete, null, modifier = Modifier.size(15.dp)) }
            )
        }
        Box(Modifier.fillMaxWidth().height(1.dp).background(SaltTheme.colors.stroke))
        parsed?.let { obj ->
            listOf(
                "判断上下文" to obj.string("context"),
                "经验正文" to obj.string("insight"),
                "适用条件" to obj.string("applicability"),
                "反例/边界" to obj.string("counterexample"),
                "质量说明" to obj.string("quality_note"),
                "来源模型" to obj.string("source_model")
            ).filter { it.second.isNotBlank() }.forEach { (label, value) ->
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    LocalizedText(label, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText, fontWeight = FontWeight.Medium)
                    SelectionContainer { LocalizedText(value, style = SaltTheme.textStyles.paragraph) }
                }
            }
            val tags = obj.array("tags").map { it.toString().trim('"') }
            if (tags.isNotEmpty()) {
                LocalizedText("标签：${tags.joinToString(" · ")}", style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
            }
        }
    }
}
