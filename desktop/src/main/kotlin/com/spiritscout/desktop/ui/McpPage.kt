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
import androidx.compose.material.icons.outlined.Edit
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.Settings
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
import com.moriafly.salt.ui.Switcher
import com.moriafly.salt.ui.Text
import com.moriafly.salt.ui.UnstableSaltUiApi
import com.spiritscout.desktop.AppController
import com.spiritscout.desktop.state.McpItem

@OptIn(UnstableSaltUiApi::class)
@Composable
fun McpPage(controller: AppController) {
    val catalog = controller.mcp
    var query by remember { mutableStateOf("") }
    var transport by remember { mutableStateOf("") }
    var risk by remember { mutableStateOf("") }
    var enabled by remember { mutableStateOf<Boolean?>(null) }
    var editing by remember { mutableStateOf<McpItem?>(null) }
    var adding by remember { mutableStateOf(false) }
    var deleteConfirm by remember { mutableStateOf("") }
    LaunchedEffect(Unit) { catalog.refresh() }

    Column(Modifier.fillMaxSize().padding(24.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                LocalizedText("MCP 管理", style = SaltTheme.textStyles.largeTitle)
                LocalizedText(
                    "管理本地和远程工具服务器；密钥、headers 和 env 不回显，配置对新会话生效。",
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
                text = "添加 MCP",
                leadingIcon = { Icon(Icons.Outlined.Add, null, modifier = Modifier.size(15.dp)) }
            )
        }
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(7.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Box(Modifier.weight(1f)) {
                SpiritTextField(query, { query = it }, "搜索 MCP 名称、命令或地址…")
            }
            LocalizedButton(
                onClick = { catalog.applyFilters(query, transport, risk, enabled) },
                text = "搜索",
                appearance = ButtonAppearance.Subtle
            )
            LocalizedButton(
                onClick = {
                    query = ""
                    transport = ""
                    risk = ""
                    enabled = null
                    catalog.applyFilters("", "", "", null)
                },
                text = "清空",
                appearance = ButtonAppearance.Subtle
            )
        }
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
            LocalizedText("传输", style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
            listOf("" to "全部", "stdio" to "STDIO", "http" to "HTTP", "sse" to "SSE").forEach { (value, label) ->
                LocalizedButton(
                    onClick = { transport = value },
                    text = label,
                    appearance = if (transport == value) ButtonAppearance.Filled else ButtonAppearance.Subtle
                )
            }
            Spacer(Modifier.width(8.dp))
            LocalizedText("风险", style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
            listOf("" to "全部", "readonly" to "只读", "intrusive" to "侵入", "destructive" to "破坏").forEach { (value, label) ->
                LocalizedButton(
                    onClick = { risk = value },
                    text = label,
                    appearance = if (risk == value) ButtonAppearance.Filled else ButtonAppearance.Subtle
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
        catalog.error?.let { ErrorBlock(it) }
        if (catalog.message.isNotBlank()) {
            LocalizedText(catalog.message, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.success)
        }
        Card(Modifier.fillMaxSize(), color = SaltTheme.colors.subBackground) {
            if (catalog.items.isEmpty()) {
                EmptyState("暂无 MCP", "添加 stdio、HTTP 或 SSE 工具服务器。")
            } else {
                LazyColumn(
                    modifier = Modifier.fillMaxSize(),
                    contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    items(catalog.items, key = { it.id }) { item ->
                        McpRow(
                            item = item,
                            deleteConfirm = deleteConfirm == item.id,
                            onEdit = { editing = item },
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

    if (adding || editing != null) {
        McpDialog(controller, editing) {
            adding = false
            editing = null
        }
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun McpRow(
    item: McpItem,
    deleteConfirm: Boolean,
    onEdit: () -> Unit,
    onDelete: () -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(SaltTheme.colors.background.copy(alpha = 0.5f))
            .padding(14.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Box(
            modifier = Modifier.size(36.dp).clip(RoundedCornerShape(8.dp))
                .background(SaltTheme.colors.highlight.copy(alpha = 0.12f)),
            contentAlignment = Alignment.Center
        ) {
            Icon(Icons.Outlined.Settings, null, modifier = Modifier.size(18.dp), tint = SaltTheme.colors.highlight)
        }
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                LocalizedText(item.id, fontWeight = FontWeight.SemiBold)
                StatusPill(if (item.enabled) "已启用" else "已停用", if (item.enabled) SaltTheme.colors.success else SaltTheme.colors.subText)
                StatusPill(item.defaultRisk.ifBlank { "风险未设" }, riskColor(item.defaultRisk))
            }
            LocalizedText(
                when (item.transport) {
                    "stdio" -> "STDIO · ${item.command.ifBlank { "命令未填" }}"
                    else -> "${item.transport.uppercase()} · ${item.url.ifBlank { "地址未填" }}"
                },
                style = SaltTheme.textStyles.sub,
                color = SaltTheme.colors.subText
            )
            LocalizedText(
                listOf(
                    "超时 ${item.timeout.toInt()}s",
                    if (item.riskByAction) "按动作审批" else "按工具风险",
                    if (item.allowedAgents.isEmpty()) "默认 Agent 范围" else "额外 Agent ${item.allowedAgents.size}",
                    if (item.targetParams.isEmpty()) "无目标参数" else "目标参数 ${item.targetParams.size}"
                ).joinToString(" · "),
                style = SaltTheme.textStyles.sub,
                color = SaltTheme.colors.subText
            )
        }
        LocalizedButton(
            onClick = onEdit,
            text = "编辑",
            appearance = ButtonAppearance.Subtle,
            leadingIcon = { Icon(Icons.Outlined.Edit, null, modifier = Modifier.size(14.dp)) }
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

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun McpDialog(
    controller: AppController,
    existing: McpItem?,
    onClose: () -> Unit
) {
    val catalog = controller.mcp
    var name by remember(existing?.id) { mutableStateOf(existing?.id.orEmpty()) }
    var transport by remember(existing?.id) { mutableStateOf(existing?.transport ?: "stdio") }
    var command by remember(existing?.id) { mutableStateOf(existing?.command.orEmpty()) }
    var args by remember(existing?.id) { mutableStateOf(existing?.args?.joinToString("\n").orEmpty()) }
    var url by remember(existing?.id) { mutableStateOf(existing?.url.orEmpty()) }
    var env by remember(existing?.id) { mutableStateOf("") }
    var headers by remember(existing?.id) { mutableStateOf("") }
    var timeout by remember(existing?.id) { mutableStateOf((existing?.timeout ?: 180.0).toInt().toString()) }
    var defaultRisk by remember(existing?.id) { mutableStateOf(existing?.defaultRisk ?: "intrusive") }
    var riskByAction by remember(existing?.id) { mutableStateOf(existing?.riskByAction ?: false) }
    var internetSearch by remember(existing?.id) { mutableStateOf(existing?.internetSearch ?: false) }
    var scopeEnforcement by remember(existing?.id) { mutableStateOf(existing?.scopeEnforcement ?: "required") }
    var targetParams by remember(existing?.id) { mutableStateOf(existing?.targetParams?.joinToString(",").orEmpty()) }
    var allowedAgents by remember(existing?.id) { mutableStateOf(existing?.allowedAgents?.toSet().orEmpty()) }
    var riskOverrides by remember(existing?.id) { mutableStateOf("") }
    var enabled by remember(existing?.id) { mutableStateOf(existing?.enabled ?: false) }
    val agentOptions = listOf(
        "verifier", "business_context", "ctf_web", "ctf_pwn",
        "ctf_reverse", "ctf_crypto", "ctf_misc"
    )

    LocalizedDialogWindow(
        onCloseRequest = onClose,
        title = if (existing == null) "添加 MCP" else "编辑 ${existing.id}",
        state = rememberDialogState(
            size = DpSize(780.dp, 820.dp),
            position = WindowPosition.Aligned(Alignment.Center)
        ),
        resizable = false
    ) {
        SaltTheme(configs = SaltConfigs.default(isDarkTheme = controller.darkTheme)) {
            Column(
                Modifier.fillMaxSize().background(SaltTheme.colors.background).padding(22.dp)
                    .verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                LocalizedText(if (existing == null) "添加 MCP" else "编辑 ${existing.id}", style = SaltTheme.textStyles.largeTitle)
                LabeledLine("名称") {
                    SpiritTextField(name, { name = it }, "字母、数字、下划线或短横线")
                }
                LabeledLine("传输类型") {
                    LazyRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        items(listOf("stdio", "http", "sse")) { value ->
                            LocalizedButton(
                                onClick = { transport = value },
                                text = value.uppercase(),
                                appearance = if (transport == value) ButtonAppearance.Filled else ButtonAppearance.Subtle
                            )
                        }
                    }
                }
                if (transport == "stdio") {
                    LabeledLine("命令") { SpiritTextField(command, { command = it }, "可执行文件或启动命令") }
                    LabeledLine("参数（每行一个）") {
                        SpiritTextField(args, { args = it }, "--stdio\n--config\n...", singleLine = false)
                    }
                } else {
                    LabeledLine("URL") { SpiritTextField(url, { url = it }, "https://host/mcp 或 /sse") }
                }
                LabeledLine("Headers（每行 KEY=VALUE，留空保持现有）") {
                    SpiritTextField(headers, { headers = it }, "Authorization=Bearer ...", singleLine = false)
                }
                LabeledLine("环境变量（每行 KEY=VALUE，留空保持现有）") {
                    SpiritTextField(env, { env = it }, "TOKEN=...", singleLine = false)
                }
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Box(Modifier.weight(1f)) {
                        LabeledLine("超时（秒）") { SpiritTextField(timeout, { timeout = it }, "180") }
                    }
                    Box(Modifier.weight(1f)) {
                        LabeledLine("目标参数（逗号分隔）") {
                            SpiritTextField(targetParams, { targetParams = it }, "url,target,host")
                        }
                    }
                }
                LabeledLine("默认风险") {
                    LazyRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        items(listOf("readonly", "intrusive", "destructive")) { value ->
                            LocalizedButton(
                                onClick = { defaultRisk = value },
                                text = value,
                                appearance = if (defaultRisk == value) ButtonAppearance.Filled else ButtonAppearance.Subtle
                            )
                        }
                    }
                }
                LabeledLine("适用范围策略") {
                    LazyRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        items(listOf("required", "best_effort", "none")) { value ->
                            LocalizedButton(
                                onClick = { scopeEnforcement = value },
                                text = value,
                                appearance = if (scopeEnforcement == value) ButtonAppearance.Filled else ButtonAppearance.Subtle
                            )
                        }
                    }
                }
                LabeledLine("额外允许的 Agent") {
                    LazyRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        items(agentOptions) { agent ->
                            LocalizedButton(
                                onClick = {
                                    allowedAgents = if (agent in allowedAgents) {
                                        allowedAgents - agent
                                    } else {
                                        allowedAgents + agent
                                    }
                                },
                                text = agent,
                                appearance = if (agent in allowedAgents) {
                                    ButtonAppearance.Filled
                                } else {
                                    ButtonAppearance.Subtle
                                }
                            )
                        }
                    }
                }
                LabeledLine("单工具风险覆盖（每行 工具名=readonly/intrusive/destructive）") {
                    SpiritTextField(
                        riskOverrides,
                        { riskOverrides = it },
                        "browser_click=intrusive",
                        singleLine = false
                    )
                }
                SwitchLine("按动作审批", "使用模型声明的动作风险，避免工具能力直接放大审批。", riskByAction) {
                    riskByAction = it
                }
                SwitchLine("公开互联网搜索", "此 MCP 仅用于公开网页搜索服务。", internetSearch) {
                    internetSearch = it
                }
                SwitchLine("启用 MCP", "配置对新启动会话生效，不热替换运行中的连接。", enabled) {
                    enabled = it
                }
                catalog.error?.let { LocalizedText(it, color = SaltTheme.colors.error, style = SaltTheme.textStyles.sub) }
                Spacer(Modifier.height(8.dp))
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                    LocalizedButton(onClick = onClose, text = "取消", appearance = ButtonAppearance.Subtle)
                    Spacer(Modifier.width(8.dp))
                    LocalizedButton(
                        onClick = {
                            catalog.save(
                                original = existing,
                                name = name,
                                transport = transport,
                                command = command,
                                argsText = args,
                                url = url,
                                envText = env,
                                headersText = headers,
                                timeoutText = timeout,
                                defaultRisk = defaultRisk,
                                riskByAction = riskByAction,
                                internetSearch = internetSearch,
                                scopeEnforcement = scopeEnforcement,
                                targetParamsText = targetParams,
                                allowedAgents = allowedAgents.toList(),
                                riskOverrideText = riskOverrides,
                                enabled = enabled
                            )
                            onClose()
                        },
                        text = "保存 MCP",
                        enabled = !catalog.saving
                    )
                }
            }
        }
    }
}

@Composable
private fun LabeledLine(label: String, content: @Composable () -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        LocalizedText(label, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
        content()
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun SwitchLine(
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

@Composable
private fun riskColor(value: String) = when (value) {
    "readonly" -> SaltTheme.colors.success
    "destructive" -> SaltTheme.colors.error
    else -> SaltTheme.colors.warning
}
