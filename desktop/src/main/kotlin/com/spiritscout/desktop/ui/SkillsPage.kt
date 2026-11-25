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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Add
import androidx.compose.material.icons.outlined.Delete
import androidx.compose.material.icons.outlined.Download
import androidx.compose.material.icons.outlined.Edit
import androidx.compose.material.icons.outlined.FileOpen
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.Save
import androidx.compose.material.icons.outlined.UploadFile
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
import com.moriafly.salt.ui.Switcher
import com.moriafly.salt.ui.Text
import com.moriafly.salt.ui.UnstableSaltUiApi
import com.spiritscout.desktop.AppController
import com.spiritscout.desktop.state.SkillDetailState
import com.spiritscout.desktop.state.SkillSummaryItem
import java.net.URLEncoder
import java.nio.charset.StandardCharsets
import javax.swing.JFileChooser
import javax.swing.filechooser.FileNameExtensionFilter

@OptIn(UnstableSaltUiApi::class)
@Composable
fun SkillsPage(controller: AppController) {
    val library = controller.skills
    var query by remember { mutableStateOf("") }
    var source by remember { mutableStateOf("") }
    var tier by remember { mutableStateOf("") }
    var enabled by remember { mutableStateOf<Boolean?>(null) }
    var showCreate by remember { mutableStateOf(false) }
    var showEdit by remember { mutableStateOf<SkillDetailState?>(null) }
    var deleteConfirm by remember { mutableStateOf("") }
    LaunchedEffect(Unit) { library.refresh() }

    Column(Modifier.fillMaxSize().padding(24.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                LocalizedText("Skill 管理", style = SaltTheme.textStyles.largeTitle)
                LocalizedText(
                    "编辑 Skill 文件和 SKILL.md；文件只保存在资源库，不执行包内脚本。",
                    style = SaltTheme.textStyles.sub,
                    color = SaltTheme.colors.subText
                )
            }
            LocalizedButton(
                onClick = {
                    val chooser = JFileChooser().apply {
                        dialogTitle = "导入 Skill ZIP"
                        fileFilter = FileNameExtensionFilter("Skill 压缩包 (*.zip)", "zip")
                    }
                    if (chooser.showOpenDialog(null) == JFileChooser.APPROVE_OPTION) {
                        chooser.selectedFile?.toPath()?.let(library::importArchive)
                    }
                },
                text = "导入 ZIP",
                appearance = ButtonAppearance.Subtle,
                enabled = !library.saving,
                leadingIcon = { Icon(Icons.Outlined.UploadFile, null, modifier = Modifier.size(15.dp)) }
            )
            Spacer(Modifier.width(8.dp))
            LocalizedButton(
                onClick = { showCreate = true },
                text = "新建 Skill",
                leadingIcon = { Icon(Icons.Outlined.Add, null, modifier = Modifier.size(15.dp)) }
            )
        }
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(7.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Box(Modifier.weight(1f)) {
                SpiritTextField(query, { query = it }, "搜索 Skill ID、描述或标签…")
            }
            LocalizedButton(
                onClick = {
                    library.applyFilters(query, source, tier, enabled)
                },
                text = "搜索",
                appearance = ButtonAppearance.Subtle
            )
            LocalizedButton(
                onClick = {
                    query = ""
                    source = ""
                    tier = ""
                    enabled = null
                    library.applyFilters("", "", "", null)
                },
                text = "清空",
                appearance = ButtonAppearance.Subtle
            )
            LocalizedButton(
                onClick = library::refresh,
                text = "刷新",
                appearance = ButtonAppearance.Subtle,
                leadingIcon = { Icon(Icons.Outlined.Refresh, null, modifier = Modifier.size(15.dp)) }
            )
        }
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            LocalizedText("来源", style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
            listOf("" to "全部", "builtin" to "内置", "archive" to "导入", "manual" to "手动").forEach { (value, label) ->
                LocalizedButton(
                    onClick = { source = value },
                    text = label,
                    appearance = if (source == value) ButtonAppearance.Filled else ButtonAppearance.Subtle
                )
            }
            Spacer(Modifier.width(8.dp))
            LocalizedText("层级", style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
            listOf("" to "全部", "core" to "Core", "domain" to "Domain", "reference" to "Reference")
                .forEach { (value, label) ->
                    LocalizedButton(
                        onClick = { tier = value },
                        text = label,
                        appearance = if (tier == value) ButtonAppearance.Filled else ButtonAppearance.Subtle
                    )
                }
            Spacer(Modifier.width(8.dp))
            LocalizedButton(
                onClick = { enabled = if (enabled == null) true else if (enabled == true) false else null },
                text = when (enabled) {
                    null -> "启停：全部"
                    true -> "启停：已启用"
                    false -> "启停：已停用"
                },
                appearance = if (enabled == null) ButtonAppearance.Subtle else ButtonAppearance.Filled
            )
        }
        library.error?.let { ErrorBlock(it) }
        if (library.actionMessage.isNotBlank()) {
            LocalizedText(library.actionMessage, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.success)
        }
        Row(Modifier.fillMaxSize(), horizontalArrangement = Arrangement.spacedBy(14.dp)) {
            Card(Modifier.width(410.dp).fillMaxHeight(), color = SaltTheme.colors.subBackground) {
                Column(Modifier.fillMaxSize()) {
                    Row(
                        Modifier.fillMaxWidth().padding(horizontal = 15.dp, vertical = 12.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        LocalizedText(
                            "${library.items.size} 个 Skill",
                            modifier = Modifier.weight(1f),
                            fontWeight = FontWeight.SemiBold
                        )
                        if (library.loading) {
                            LocalizedText("同步中…", style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
                        }
                    }
                    Box(Modifier.fillMaxWidth().height(1.dp).background(SaltTheme.colors.stroke))
                    if (library.items.isEmpty()) {
                        EmptyState("暂无 Skill", "新建、导入 ZIP，或清空筛选条件。")
                    } else {
                        LazyColumn(
                            modifier = Modifier.fillMaxSize(),
                            contentPadding = androidx.compose.foundation.layout.PaddingValues(12.dp),
                            verticalArrangement = Arrangement.spacedBy(7.dp)
                        ) {
                            items(library.items, key = { it.id }) { skill ->
                                SkillListRow(
                                    skill = skill,
                                    selected = library.selectedSkill?.id == skill.id,
                                    onClick = { library.selectSkill(skill.id) }
                                )
                            }
                        }
                    }
                }
            }
            Card(Modifier.weight(1f).fillMaxHeight(), color = SaltTheme.colors.subBackground) {
                SkillDetailPanel(
                    controller = controller,
                    deleteConfirm = deleteConfirm,
                    onDeleteConfirm = { deleteConfirm = it },
                    onEdit = { showEdit = it }
                )
            }
        }
    }

    if (showCreate) {
        SkillConfigDialog(controller, null) { showCreate = false }
    }
    showEdit?.let { detail ->
        SkillConfigDialog(controller, detail) { showEdit = null }
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun SkillListRow(
    skill: SkillSummaryItem,
    selected: Boolean,
    onClick: () -> Unit
) {
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
            LocalizedText(skill.id, modifier = Modifier.weight(1f), fontWeight = FontWeight.SemiBold)
            StatusPill(
                if (skill.enabled) "已启用" else "已停用",
                if (skill.enabled) SaltTheme.colors.success else SaltTheme.colors.subText
            )
        }
        LocalizedText(
            skill.description.ifBlank { "暂无描述" },
            style = SaltTheme.textStyles.sub,
            color = SaltTheme.colors.subText,
            maxLines = 2
        )
        LocalizedText(
            listOf(skill.domain, skill.tier, skill.sourceKind, "v${skill.version}")
                .filter(String::isNotBlank).joinToString(" · "),
            style = SaltTheme.textStyles.sub,
            color = SaltTheme.colors.subText
        )
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun SkillDetailPanel(
    controller: AppController,
    deleteConfirm: String,
    onDeleteConfirm: (String) -> Unit,
    onEdit: (SkillDetailState) -> Unit
) {
    val library = controller.skills
    val detail = library.selectedSkill
    if (detail == null) {
        EmptyState("选择一个 Skill", "查看文件树、SKILL.md 内容并直接保存修改。")
        return
    }
    val paths = detail.files.keys.sortedWith(
        compareBy<String> { if (it == "SKILL.md") 0 else 1 }.thenBy { it }
    )
    var selectedPath by remember(detail.id) {
        mutableStateOf(paths.firstOrNull().orEmpty())
    }
    var editing by remember(detail.id, selectedPath) { mutableStateOf(false) }
    var draft by remember(detail.id, selectedPath) {
        mutableStateOf(detail.files[selectedPath].orEmpty())
    }
    LaunchedEffect(detail.version) {
        if (!editing) {
            draft = detail.files[selectedPath].orEmpty()
        }
    }

    Column(Modifier.fillMaxSize()) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                LocalizedText(detail.id, fontWeight = FontWeight.SemiBold)
                LocalizedText(
                    listOf(detail.domain, detail.tier, detail.sourceKind, "版本 ${detail.version}")
                        .filter(String::isNotBlank).joinToString(" · "),
                    style = SaltTheme.textStyles.sub,
                    color = SaltTheme.colors.subText
                )
            }
            LocalizedButton(
                onClick = { onEdit(detail) },
                text = "编辑配置",
                appearance = ButtonAppearance.Subtle,
                leadingIcon = { Icon(Icons.Outlined.Edit, null, modifier = Modifier.size(15.dp)) }
            )
            Spacer(Modifier.width(6.dp))
            LocalizedButton(
                onClick = {
                    controller.openBackendUrl("/api/resources/skills/${urlPart(detail.id)}/export")
                },
                text = "导出 ZIP",
                appearance = ButtonAppearance.Subtle,
                leadingIcon = { Icon(Icons.Outlined.Download, null, modifier = Modifier.size(15.dp)) }
            )
            Spacer(Modifier.width(6.dp))
            LocalizedButton(
                onClick = {
                    if (deleteConfirm == detail.id) {
                        library.deleteSkill(detail.id)
                        onDeleteConfirm("")
                    } else {
                        onDeleteConfirm(detail.id)
                    }
                },
                text = if (deleteConfirm == detail.id) "确认删除" else "删除",
                appearance = ButtonAppearance.Subtle,
                intent = ButtonIntent.Destructive,
                leadingIcon = { Icon(Icons.Outlined.Delete, null, modifier = Modifier.size(15.dp)) }
            )
        }
        Box(Modifier.fillMaxWidth().height(1.dp).background(SaltTheme.colors.stroke))
        Row(Modifier.fillMaxSize()) {
            Column(
                modifier = Modifier
                    .width(210.dp)
                    .fillMaxHeight()
                    .background(SaltTheme.colors.background.copy(alpha = 0.35f))
                    .padding(10.dp),
                verticalArrangement = Arrangement.spacedBy(5.dp)
            ) {
                LocalizedText("${detail.id}/", style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
                LazyColumn(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    items(paths, key = { it }) { path ->
                        val depth = path.count { it == '/' }
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clip(RoundedCornerShape(6.dp))
                                .background(
                                    if (selectedPath == path) SaltTheme.colors.highlight.copy(alpha = 0.12f)
                                    else SaltTheme.colors.background.copy(alpha = 0.35f)
                                )
                                .clickable {
                                    if (editing && draft != detail.files[selectedPath]) {
                                        editing = false
                                    }
                                    selectedPath = path
                                    draft = detail.files[path].orEmpty()
                                }
                                .padding(start = (8 + depth * 12).dp, top = 7.dp, bottom = 7.dp, end = 8.dp),
                            horizontalArrangement = Arrangement.spacedBy(6.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Icon(
                                Icons.Outlined.FileOpen,
                                null,
                                modifier = Modifier.size(14.dp),
                                tint = if (selectedPath == path) SaltTheme.colors.highlight else SaltTheme.colors.subText
                            )
                            LocalizedText(path.substringAfterLast('/'), style = SaltTheme.textStyles.sub)
                        }
                    }
                }
            }
            Box(Modifier.width(1.dp).fillMaxHeight().background(SaltTheme.colors.stroke))
            Column(Modifier.weight(1f).fillMaxHeight()) {
                Row(
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 13.dp, vertical = 9.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    LocalizedText(
                        selectedPath,
                        modifier = Modifier.weight(1f),
                        fontFamily = FontFamily.Monospace,
                        style = SaltTheme.textStyles.sub
                    )
                    if (!editing) {
                        LocalizedButton(
                            onClick = { editing = true; draft = detail.files[selectedPath].orEmpty() },
                            text = "编辑",
                            appearance = ButtonAppearance.Subtle
                        )
                    } else {
                        LocalizedButton(
                            onClick = {
                                editing = false
                                draft = detail.files[selectedPath].orEmpty()
                            },
                            text = "取消",
                            appearance = ButtonAppearance.Subtle
                        )
                        Spacer(Modifier.width(6.dp))
                        LocalizedButton(
                            onClick = { library.saveFile(selectedPath, draft) },
                            text = if (library.saving) "保存中…" else "保存",
                            enabled = !library.saving && draft != detail.files[selectedPath],
                            leadingIcon = { Icon(Icons.Outlined.Save, null, modifier = Modifier.size(15.dp)) }
                        )
                    }
                }
                Box(Modifier.fillMaxWidth().height(1.dp).background(SaltTheme.colors.stroke))
                if (editing) {
                    Row(
                        modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 7.dp),
                        horizontalArrangement = Arrangement.spacedBy(6.dp)
                    ) {
                        listOf(
                            "粗体" to "\n**粗体文本**",
                            "斜体" to "\n*斜体文本*",
                            "标题" to "\n## 小标题",
                            "列表" to "\n- 列表项",
                            "代码块" to "\n```text\n代码\n```"
                        ).forEach { (label, snippet) ->
                            LocalizedButton(
                                onClick = { draft = draft.trimEnd() + snippet },
                                text = label,
                                appearance = ButtonAppearance.Subtle
                            )
                        }
                    }
                    SpiritTextField(
                        draft,
                        { draft = it },
                        "编辑文件内容",
                        modifier = Modifier.fillMaxSize().padding(12.dp),
                        singleLine = false
                    )
                } else {
                    SelectionContainerText(draft, selectedPath)
                }
            }
        }
    }
}

@Composable
private fun SelectionContainerText(content: String, path: String) {
    if (path.endsWith(".md", true)) {
        MarkdownView(
            if (content.isBlank()) "（空文件）" else content,
            Modifier.fillMaxSize().padding(12.dp)
        )
    } else {
        androidx.compose.foundation.text.selection.SelectionContainer {
            LocalizedText(
                if (content.isBlank()) "（空文件）" else content,
                modifier = Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
                fontFamily = FontFamily.Monospace,
                style = SaltTheme.textStyles.paragraph
            )
        }
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun SkillConfigDialog(
    controller: AppController,
    detail: SkillDetailState?,
    onClose: () -> Unit
) {
    val library = controller.skills
    var skillId by remember(detail?.id) { mutableStateOf(detail?.id.orEmpty()) }
    var description by remember(detail?.id) { mutableStateOf(detail?.description.orEmpty()) }
    var domain by remember(detail?.id) { mutableStateOf(detail?.domain ?: "custom") }
    var tier by remember(detail?.id) { mutableStateOf(detail?.tier ?: "domain") }
    var enabled by remember(detail?.id) { mutableStateOf(detail?.enabled ?: true) }
    var newBody by remember { mutableStateOf("") }

    LocalizedDialogWindow(
        onCloseRequest = onClose,
        title = if (detail == null) "新建 Skill" else "编辑 Skill",
        state = rememberDialogState(
            size = DpSize(700.dp, 650.dp),
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
                    if (detail == null) "新建 Skill" else "编辑 ${detail.id}",
                    style = SaltTheme.textStyles.largeTitle
                )
                LabeledField("Skill ID") {
                    SpiritTextField(
                        skillId,
                        { skillId = it },
                        "字母、数字、下划线和短横线"
                    )
                }
                LabeledField("描述") {
                    SpiritTextField(description, { description = it }, "说明适用条件和能力")
                }
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Box(Modifier.weight(1f)) {
                        LabeledField("领域") {
                            SpiritTextField(domain, { domain = it }, "例如 web、crypto、custom")
                        }
                    }
                    Box(Modifier.weight(1f)) {
                        LabeledField("层级") {
                            LazyRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                items(listOf("core", "domain", "reference")) { value ->
                                    LocalizedButton(
                                        onClick = { tier = value },
                                        text = value,
                                        appearance = if (tier == value) {
                                            ButtonAppearance.Filled
                                        } else {
                                            ButtonAppearance.Subtle
                                        }
                                    )
                                }
                            }
                        }
                    }
                }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        LocalizedText("启用 Skill", fontWeight = FontWeight.Medium)
                        LocalizedText(
                            "停用后不会参与 SkillRuntime 检索。",
                            style = SaltTheme.textStyles.sub,
                            color = SaltTheme.colors.subText
                        )
                    }
                    Switcher(state = enabled, onChange = { enabled = it })
                }
                if (detail == null) {
                    LabeledField("SKILL.md") {
                        SpiritTextField(newBody, { newBody = it }, "编写 SKILL.md 内容", singleLine = false)
                    }
                } else {
                    LocalizedText(
                        "正文和 references/scripts 文件请在文件浏览器中编辑。",
                        style = SaltTheme.textStyles.sub,
                        color = SaltTheme.colors.subText
                    )
                }
                library.error?.let {
                    LocalizedText(it, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.error)
                }
                Spacer(Modifier.weight(1f))
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                    LocalizedButton(onClick = onClose, text = "取消", appearance = ButtonAppearance.Subtle)
                    Spacer(Modifier.width(8.dp))
                    LocalizedButton(
                        onClick = {
                            library.saveSkill(
                                originalId = detail?.id,
                                skillId = skillId,
                                description = description,
                                domain = domain,
                                tier = tier,
                                enabled = enabled,
                                body = newBody
                            )
                            onClose()
                        },
                        text = "保存配置",
                        enabled = !library.saving
                    )
                }
            }
        }
    }
}

@Composable
private fun LabeledField(label: String, content: @Composable () -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        LocalizedText(label, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
        content()
    }
}

private fun urlPart(value: String): String =
    URLEncoder.encode(value, StandardCharsets.UTF_8)
