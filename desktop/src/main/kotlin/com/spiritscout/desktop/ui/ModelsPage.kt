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
import androidx.compose.foundation.layout.heightIn
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
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material.icons.outlined.Sync
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
import com.spiritscout.desktop.model.objectOrEmpty
import com.spiritscout.desktop.model.string
import com.spiritscout.desktop.state.ModelItem
import com.spiritscout.desktop.state.ProviderItem

@OptIn(UnstableSaltUiApi::class)
@Composable
fun ModelsPage(controller: AppController) {
    val catalog = controller.modelProviders
    var editingProvider by remember { mutableStateOf<ProviderItem?>(null) }
    var addingProvider by remember { mutableStateOf(false) }
    var editingModel by remember { mutableStateOf<ModelItem?>(null) }
    var addingModelFor by remember { mutableStateOf<String?>(null) }
    var fetchingProvider by remember { mutableStateOf<ProviderItem?>(null) }
    var selectedProvider by remember { mutableStateOf("") }
    var deleteProviderConfirm by remember { mutableStateOf("") }
    var deleteModelConfirm by remember { mutableStateOf("") }

    LaunchedEffect(Unit) { catalog.open() }
    LaunchedEffect(catalog.providers.map { it.name }) {
        if (catalog.providers.none { it.name == selectedProvider }) {
            selectedProvider = catalog.providers.firstOrNull()?.name.orEmpty()
        }
    }

    Column(Modifier.fillMaxSize().padding(24.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                LocalizedText("模型与供应商", style = SaltTheme.textStyles.largeTitle)
                LocalizedText(
                    "供应商保存端点和加密密钥；模型描述能力、上下文、思考档、缓存和 fallback。",
                    style = SaltTheme.textStyles.sub,
                    color = SaltTheme.colors.subText
                )
            }
            LocalizedButton(
                onClick = catalog::open,
                text = "刷新",
                appearance = ButtonAppearance.Subtle,
                leadingIcon = { Icon(Icons.Outlined.Refresh, null, modifier = Modifier.size(15.dp)) }
            )
            Spacer(Modifier.width(8.dp))
            LocalizedButton(
                onClick = { addingProvider = true },
                text = "添加供应商",
                leadingIcon = { Icon(Icons.Outlined.Add, null, modifier = Modifier.size(15.dp)) }
            )
        }
        catalog.error?.let { ErrorBlock(it) }
        if (catalog.actionMessage.isNotBlank()) {
            LocalizedText(catalog.actionMessage, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.success)
        }
        NamingChainBar(controller)
        Row(Modifier.fillMaxSize(), horizontalArrangement = Arrangement.spacedBy(14.dp)) {
            Card(Modifier.width(390.dp).fillMaxHeight(), color = SaltTheme.colors.subBackground) {
                Column(Modifier.fillMaxSize()) {
                    Row(
                        Modifier.fillMaxWidth().padding(horizontal = 15.dp, vertical = 12.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        LocalizedText(
                            "${catalog.providers.size} 个供应商",
                            modifier = Modifier.weight(1f),
                            fontWeight = FontWeight.SemiBold
                        )
                        if (catalog.loading) {
                            LocalizedText("同步中…", style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
                        }
                    }
                    Box(Modifier.fillMaxWidth().height(1.dp).background(SaltTheme.colors.stroke))
                    if (catalog.providers.isEmpty()) {
                        EmptyState("暂无供应商", "添加供应商后即可获取模型或手动添加模型 ID。")
                    } else {
                        LazyColumn(
                            modifier = Modifier.fillMaxSize(),
                            contentPadding = androidx.compose.foundation.layout.PaddingValues(12.dp),
                            verticalArrangement = Arrangement.spacedBy(8.dp)
                        ) {
                            items(catalog.providers, key = { it.name }) { provider ->
                                ProviderRow(
                                    provider = provider,
                                    modelCount = catalog.models.count { it.providerRef == provider.name },
                                    selected = selectedProvider == provider.name,
                                    deleteConfirm = deleteProviderConfirm == provider.name,
                                    onSelect = {
                                        selectedProvider = provider.name
                                    },
                                    onEdit = { editingProvider = provider },
                                    onFetch = { fetchingProvider = provider },
                                    onQuota = { catalog.loadQuota(provider.name) },
                                    onOAuthStart = { catalog.startOAuth(provider.name) },
                                    onOAuthPoll = { catalog.pollOAuth(provider.name) },
                                    onOAuthLogout = { catalog.logoutOAuth(provider.name) },
                                    onDelete = {
                                        if (deleteProviderConfirm == provider.name) {
                                            catalog.deleteProvider(provider.name)
                                            deleteProviderConfirm = ""
                                        } else {
                                            deleteProviderConfirm = provider.name
                                        }
                                    }
                                )
                            }
                        }
                    }
                }
            }
            Card(Modifier.weight(1f).fillMaxHeight(), color = SaltTheme.colors.subBackground) {
                ModelList(
                    controller = controller,
                    providerName = selectedProvider,
                    deleteConfirm = deleteModelConfirm,
                    onAdd = { addingModelFor = selectedProvider },
                    onEdit = { editingModel = it },
                    onDelete = { model ->
                        if (deleteModelConfirm == model.key) {
                            catalog.deleteModel(model.key)
                            deleteModelConfirm = ""
                        } else {
                            deleteModelConfirm = model.key
                        }
                    }
                )
            }
        }
    }

    if (addingProvider || editingProvider != null) {
        ProviderDialog(
            controller = controller,
            provider = editingProvider,
            onClose = {
                addingProvider = false
                editingProvider = null
            }
        )
    }
    if (addingModelFor != null || editingModel != null) {
        ModelDialog(
            controller = controller,
            model = editingModel,
            initialProvider = addingModelFor.orEmpty(),
            onClose = {
                addingModelFor = null
                editingModel = null
            }
        )
    }
    fetchingProvider?.let { provider ->
        FetchModelsDialog(controller, provider) { fetchingProvider = null }
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun ProviderRow(
    provider: ProviderItem,
    modelCount: Int,
    selected: Boolean,
    deleteConfirm: Boolean,
    onSelect: () -> Unit,
    onEdit: () -> Unit,
    onFetch: () -> Unit,
    onQuota: () -> Unit,
    onOAuthStart: () -> Unit,
    onOAuthPoll: () -> Unit,
    onOAuthLogout: () -> Unit,
    onDelete: () -> Unit
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(
                if (selected) SaltTheme.colors.highlight.copy(alpha = 0.1f)
                else SaltTheme.colors.background.copy(alpha = 0.5f)
            )
            .clickable(onClick = onSelect)
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(7.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            LocalizedText(provider.name, modifier = Modifier.weight(1f), fontWeight = FontWeight.SemiBold)
            ProviderKeyStatus(provider)
        }
        LocalizedText(
            "${protocolText(provider.provider)} · ${provider.baseUrl.ifBlank { "（未填 API 地址）" }}",
            style = SaltTheme.textStyles.sub,
            color = SaltTheme.colors.subText
        )
        LocalizedText(
            "$modelCount 个模型 · ${keySourceText(provider.keySource)}",
            style = SaltTheme.textStyles.sub,
            color = SaltTheme.colors.subText
        )
        LazyRow(horizontalArrangement = Arrangement.spacedBy(5.dp)) {
            item {
                LocalizedButton(
                    onClick = onFetch,
                    text = "获取模型",
                    appearance = ButtonAppearance.Subtle,
                    leadingIcon = { Icon(Icons.Outlined.Sync, null, modifier = Modifier.size(14.dp)) }
                )
            }
            item {
                LocalizedButton(
                    onClick = onQuota,
                    text = "额度",
                    appearance = ButtonAppearance.Subtle,
                    leadingIcon = { Icon(Icons.Outlined.Download, null, modifier = Modifier.size(14.dp)) }
                )
            }
            if (provider.authMethod == "kimi_oauth") {
                item {
                    LocalizedButton(
                        onClick = if (provider.authStatus == "reauth_required") onOAuthStart else onOAuthPoll,
                        text = if (provider.authStatus == "reauth_required") "OAuth 登录" else "检查 OAuth",
                        appearance = ButtonAppearance.Subtle
                    )
                }
                item {
                    LocalizedButton(
                        onClick = onOAuthLogout,
                        text = "退出 OAuth",
                        appearance = ButtonAppearance.Subtle,
                        intent = ButtonIntent.Destructive
                    )
                }
            }
            item {
                LocalizedButton(
                    onClick = onEdit,
                    text = "编辑",
                    appearance = ButtonAppearance.Subtle,
                    leadingIcon = { Icon(Icons.Outlined.Edit, null, modifier = Modifier.size(14.dp)) }
                )
            }
            item {
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
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun ProviderKeyStatus(provider: ProviderItem) {
    val ready = provider.keyConfigured && provider.authStatus != "reauth_required"
    StatusPill(
        when {
            provider.authMethod == "kimi_oauth" && ready -> "OAuth 已连接"
            provider.authMethod == "kimi_oauth" -> "OAuth 待登录"
            ready -> "密钥已就绪"
            else -> "密钥未配置"
        },
        if (ready) SaltTheme.colors.success else SaltTheme.colors.warning
    )
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun ModelList(
    controller: AppController,
    providerName: String,
    deleteConfirm: String,
    onAdd: () -> Unit,
    onEdit: (ModelItem) -> Unit,
    onDelete: (ModelItem) -> Unit
) {
    val catalog = controller.modelProviders
    val provider = catalog.providers.firstOrNull { it.name == providerName }
    val models = catalog.models.filter { it.providerRef == providerName }
    Column(Modifier.fillMaxSize()) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column(Modifier.weight(1f)) {
                LocalizedText(providerName.ifBlank { "模型" }, fontWeight = FontWeight.SemiBold)
                LocalizedText(
                    if (provider == null) "选择左侧供应商查看模型" else "${models.size} 个模型",
                    style = SaltTheme.textStyles.sub,
                    color = SaltTheme.colors.subText
                )
            }
            LocalizedButton(
                onClick = onAdd,
                text = "手动添加模型",
                enabled = providerName.isNotBlank(),
                appearance = ButtonAppearance.Subtle,
                leadingIcon = { Icon(Icons.Outlined.Add, null, modifier = Modifier.size(15.dp)) }
            )
        }
        Box(Modifier.fillMaxWidth().height(1.dp).background(SaltTheme.colors.stroke))
        catalog.quota?.let { quota ->
            QuotaPanel(quota)
        }
        catalog.oauthFlow?.let { flow ->
            OAuthPanel(flow, providerName, controller)
        }
        if (provider == null) {
            EmptyState("选择供应商", "模型按其供应商端点分组展示。")
        } else if (models.isEmpty()) {
            EmptyState("暂无模型", "获取供应商模型列表，或手动添加模型 ID。")
        } else {
            LazyColumn(
                modifier = Modifier.fillMaxSize(),
                contentPadding = androidx.compose.foundation.layout.PaddingValues(14.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                items(models, key = { it.key }) { model ->
                    ModelRow(
                        model = model,
                        deleteConfirm = deleteConfirm == model.key,
                        onTest = { controller.modelProviders.testModel(model.key) },
                        onEdit = { onEdit(model) },
                        onDelete = { onDelete(model) }
                    )
                }
            }
        }
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun ModelRow(
    model: ModelItem,
    deleteConfirm: Boolean,
    onTest: () -> Unit,
    onEdit: () -> Unit,
    onDelete: () -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(SaltTheme.colors.background.copy(alpha = 0.5f))
            .padding(12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            LocalizedText(model.model, fontWeight = FontWeight.SemiBold)
            LocalizedText(
                listOf(
                    if (model.contextWindow > 0) "上下文 ${formatContext(model.contextWindow)}" else "上下文未设",
                    model.capabilities.joinToString(" · ").ifBlank { "能力未标注" },
                    model.reasoningEfforts.joinToString(" / ").ifBlank { "默认思考档" }
                ).joinToString(" · "),
                style = SaltTheme.textStyles.sub,
                color = SaltTheme.colors.subText
            )
            if (model.fallbackFor.isNotEmpty()) {
                LocalizedText(
                    "作为 fallback：${model.fallbackFor.joinToString("、")}",
                    style = SaltTheme.textStyles.sub,
                    color = SaltTheme.colors.subText
                )
            }
        }
        LocalizedButton(onClick = onTest, text = "测试", appearance = ButtonAppearance.Subtle)
        LocalizedButton(onClick = onEdit, text = "编辑", appearance = ButtonAppearance.Subtle)
        LocalizedButton(
            onClick = onDelete,
            text = if (deleteConfirm) "确认删除" else "删除",
            appearance = ButtonAppearance.Subtle,
            intent = ButtonIntent.Destructive
        )
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun NamingChainBar(controller: AppController) {
    val catalog = controller.modelProviders
    var chain by remember(catalog.namingChain.toList()) { mutableStateOf(catalog.namingChain.toList()) }
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(SaltTheme.colors.subBackground)
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(7.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                LocalizedText("会话自动命名候选链", fontWeight = FontWeight.SemiBold)
                LocalizedText(
                    "顺序即降级顺序；留空时跟随灵枢指派。",
                    style = SaltTheme.textStyles.sub,
                    color = SaltTheme.colors.subText
                )
            }
            LocalizedButton(
                onClick = { catalog.saveNamingChain(chain) },
                text = "保存候选链",
                appearance = ButtonAppearance.Subtle,
                enabled = chain != catalog.namingChain.toList()
            )
        }
        LazyRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            if (chain.isEmpty()) {
                item { LocalizedText("未配置，使用灵枢的模型。", style = SaltTheme.textStyles.sub) }
            } else {
                items(chain) { key ->
                    val model = catalog.models.firstOrNull { it.key == key }
                    LocalizedButton(
                        onClick = { chain = chain - key },
                        text = "#${chain.indexOf(key) + 1} ${model?.model ?: key} ×",
                        appearance = ButtonAppearance.Filled
                    )
                }
            }
        }
        LazyRow(horizontalArrangement = Arrangement.spacedBy(5.dp)) {
            items(catalog.models.filter { it.key !in chain }, key = { it.key }) { model ->
                LocalizedButton(
                    onClick = { chain = chain + model.key },
                    text = "${model.providerRef} / ${model.model}",
                    appearance = ButtonAppearance.Subtle
                )
            }
        }
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun ProviderDialog(
    controller: AppController,
    provider: ProviderItem?,
    onClose: () -> Unit
) {
    val catalog = controller.modelProviders
    var name by remember(provider?.name) { mutableStateOf(provider?.name.orEmpty()) }
    var protocol by remember(provider?.name) { mutableStateOf(provider?.provider ?: "openai_compatible") }
    var baseUrl by remember(provider?.name) { mutableStateOf(provider?.baseUrl.orEmpty()) }
    var apiKey by remember(provider?.name) { mutableStateOf("") }

    LocalizedDialogWindow(
        onCloseRequest = onClose,
        title = if (provider == null) "添加供应商" else "编辑供应商",
        state = rememberDialogState(
            size = DpSize(760.dp, 680.dp),
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
                    if (provider == null) "添加供应商" else "编辑 ${provider.name}",
                    style = SaltTheme.textStyles.largeTitle
                )
                LocalizedText(
                    "密钥仅加密保存在本机 Vault，页面不会回显。",
                    style = SaltTheme.textStyles.sub,
                    color = SaltTheme.colors.subText
                )
                if (provider == null) {
                    LocalizedText("厂商预设", fontWeight = FontWeight.Medium)
                    LazyRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        items(catalog.presets, key = { it.key }) { preset ->
                            LocalizedButton(
                                onClick = {
                                    name = preset.key
                                    protocol = preset.provider
                                    baseUrl = preset.baseUrl
                                },
                                text = preset.familyName.ifBlank { preset.name } +
                                    preset.edition.takeIf(String::isNotBlank)?.let { " · $it" }.orEmpty(),
                                appearance = ButtonAppearance.Subtle
                            )
                        }
                    }
                }
                Field("供应商名称") { SpiritTextField(name, { name = it }, "唯一名称") }
                Field("协议") {
                    LazyRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        items(
                            listOf(
                            "openai_compatible" to "OpenAI 兼容",
                            "anthropic_compatible" to "Anthropic 兼容",
                            "ollama" to "Ollama 原生"
                            )
                        ) { (value, label) ->
                            LocalizedButton(
                                onClick = { protocol = value },
                                text = label,
                                appearance = if (protocol == value) ButtonAppearance.Filled else ButtonAppearance.Subtle
                            )
                        }
                    }
                }
                Field("Base URL") { SpiritTextField(baseUrl, { baseUrl = it }, "https://api.example.com/v1") }
                Field("API Key") {
                    SpiritPasswordField(apiKey, { apiKey = it }, "留空保持现有密钥不变")
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
                            catalog.saveProvider(provider?.name, name, protocol, baseUrl, apiKey)
                            onClose()
                        },
                        text = "保存供应商",
                        enabled = !catalog.actionBusy
                    )
                }
            }
        }
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun ModelDialog(
    controller: AppController,
    model: ModelItem?,
    initialProvider: String,
    onClose: () -> Unit
) {
    val catalog = controller.modelProviders
    var modelId by remember(model?.key) { mutableStateOf(model?.model.orEmpty()) }
    var providerRef by remember(model?.key) { mutableStateOf(model?.providerRef ?: initialProvider) }
    var context by remember(model?.key) { mutableStateOf(model?.contextWindow?.toString().orEmpty()) }
    var maxOutput by remember(model?.key) { mutableStateOf(model?.maxOutputTokens?.toString().orEmpty()) }
    var capabilities by remember(model?.key) { mutableStateOf(model?.capabilities?.toSet().orEmpty()) }
    var efforts by remember(model?.key) { mutableStateOf(model?.reasoningEfforts?.toSet().orEmpty()) }
    var caching by remember(model?.key) { mutableStateOf(model?.promptCaching ?: "provider_default") }
    var costInput by remember(model?.key) { mutableStateOf(formatModelNumber(model?.costInputPerMtok)) }
    var costOutput by remember(model?.key) { mutableStateOf(formatModelNumber(model?.costOutputPerMtok)) }
    var costCached by remember(model?.key) { mutableStateOf(formatModelNumber(model?.costCachedInputPerMtok)) }
    var costWrite by remember(model?.key) { mutableStateOf(formatModelNumber(model?.costCacheWritePerMtok)) }
    var rpm by remember(model?.key) { mutableStateOf((model?.rateLimitRpm ?: 60).toString()) }
    var concurrency by remember(model?.key) { mutableStateOf((model?.maxConcurrency ?: 0).toString()) }
    var quality by remember(model?.key) { mutableStateOf(formatModelNumber(model?.qualityScore ?: 1.0)) }
    var fallbackFor by remember(model?.key) { mutableStateOf(model?.fallbackFor?.joinToString(",").orEmpty()) }
    val capabilityOptions = listOf("vision", "tools", "reasoning", "json", "audio", "embedding")
    val effortOptions = listOf("minimal", "low", "medium", "high", "xhigh", "max", "ultra")

    LocalizedDialogWindow(
        onCloseRequest = onClose,
        title = if (model == null) "添加模型" else "编辑模型",
        state = rememberDialogState(
            size = DpSize(700.dp, 660.dp),
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
                    if (model == null) "添加模型" else "编辑 ${model.model}",
                    style = SaltTheme.textStyles.largeTitle
                )
                Field("模型 ID") { SpiritTextField(modelId, { modelId = it }, "例如 gpt-5.6 或 org/model") }
                Field("供应商") {
                    LazyRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        items(catalog.providers, key = { it.name }) { provider ->
                            LocalizedButton(
                                onClick = { providerRef = provider.name },
                                text = provider.name,
                                appearance = if (providerRef == provider.name) {
                                    ButtonAppearance.Filled
                                } else {
                                    ButtonAppearance.Subtle
                                }
                            )
                        }
                    }
                }
                Field("上下文窗口") { SpiritTextField(context, { context = it }, "例如 128000") }
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Box(Modifier.weight(1f)) {
                        Field("单次输出上限") { SpiritTextField(maxOutput, { maxOutput = it }, "0 = 端点默认") }
                    }
                    Box(Modifier.weight(1f)) {
                        Field("RPM") { SpiritTextField(rpm, { rpm = it }, "60") }
                    }
                    Box(Modifier.weight(1f)) {
                        Field("最大并发") { SpiritTextField(concurrency, { concurrency = it }, "0 = 全局策略") }
                    }
                }
                Field("能力") {
                    LazyRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        items(capabilityOptions) { value ->
                            LocalizedButton(
                                onClick = {
                                    capabilities = if (value in capabilities) capabilities - value else capabilities + value
                                },
                                text = value,
                                appearance = if (value in capabilities) ButtonAppearance.Filled else ButtonAppearance.Subtle
                            )
                        }
                    }
                }
                Field("思考档") {
                    LazyRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        items(effortOptions) { value ->
                            LocalizedButton(
                                onClick = {
                                    efforts = if (value in efforts) efforts - value else efforts + value
                                },
                                text = value,
                                appearance = if (value in efforts) ButtonAppearance.Filled else ButtonAppearance.Subtle
                            )
                        }
                    }
                }
                Field("缓存策略") {
                    LazyRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        items(listOf("provider_default", "automatic", "explicit", "disabled")) { value ->
                            LocalizedButton(
                                onClick = { caching = value },
                                text = value,
                                appearance = if (caching == value) ButtonAppearance.Filled else ButtonAppearance.Subtle
                            )
                        }
                    }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Box(Modifier.weight(1f)) {
                        Field("输入价格 / MTok") { SpiritTextField(costInput, { costInput = it }, "0") }
                    }
                    Box(Modifier.weight(1f)) {
                        Field("输出价格 / MTok") { SpiritTextField(costOutput, { costOutput = it }, "0") }
                    }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Box(Modifier.weight(1f)) {
                        Field("缓存命中价格") { SpiritTextField(costCached, { costCached = it }, "留空不声明") }
                    }
                    Box(Modifier.weight(1f)) {
                        Field("缓存写入价格") { SpiritTextField(costWrite, { costWrite = it }, "留空不声明") }
                    }
                    Box(Modifier.weight(1f)) {
                        Field("质量分") { SpiritTextField(quality, { quality = it }, "1.0") }
                    }
                }
                Field("作为以下模型的 fallback（逗号分隔）") {
                    SpiritTextField(fallbackFor, { fallbackFor = it }, "model-a, provider/model-b")
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
                            catalog.saveModel(
                                originalKey = model?.key,
                                model = modelId,
                                providerRef = providerRef,
                                contextWindow = context.toLongOrNull() ?: 0,
                                maxOutputTokens = maxOutput.toLongOrNull() ?: 0,
                                capabilities = capabilities.toList(),
                                reasoningEfforts = efforts.toList(),
                                promptCaching = caching,
                                costInputPerMtok = costInput.toDoubleOrNull() ?: 0.0,
                                costOutputPerMtok = costOutput.toDoubleOrNull() ?: 0.0,
                                costCachedInputPerMtok = costCached.toDoubleOrNull(),
                                costCacheWritePerMtok = costWrite.toDoubleOrNull(),
                                rateLimitRpm = rpm.toIntOrNull() ?: 60,
                                maxConcurrency = concurrency.toIntOrNull() ?: 0,
                                qualityScore = quality.toDoubleOrNull() ?: 1.0,
                                fallbackFor = fallbackFor.split(',', '，')
                                    .map(String::trim)
                                    .filter(String::isNotBlank)
                            )
                            onClose()
                        },
                        text = "保存模型",
                        enabled = !catalog.actionBusy
                    )
                }
            }
        }
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun FetchModelsDialog(
    controller: AppController,
    provider: ProviderItem,
    onClose: () -> Unit
) {
    val catalog = controller.modelProviders
    var selected by remember { mutableStateOf(setOf<String>()) }
    LaunchedEffect(provider.name) {
        catalog.fetchProviderModels(provider.name, provider.provider, provider.baseUrl)
    }
    LaunchedEffect(catalog.fetchedModels.toList()) {
        selected = catalog.fetchedModels.toSet()
    }

    LocalizedDialogWindow(
        onCloseRequest = onClose,
        title = "获取 ${provider.name} 模型",
        state = rememberDialogState(
            size = DpSize(760.dp, 640.dp),
            position = WindowPosition.Aligned(Alignment.Center)
        ),
        resizable = false
    ) {
        SaltTheme(configs = SaltConfigs.default(isDarkTheme = controller.darkTheme)) {
            Column(
                Modifier.fillMaxSize().background(SaltTheme.colors.background).padding(22.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        LocalizedText("从端点获取模型列表", style = SaltTheme.textStyles.largeTitle)
                        LocalizedText(
                            catalog.actionMessage,
                            style = SaltTheme.textStyles.sub,
                            color = SaltTheme.colors.subText
                        )
                    }
                    if (catalog.actionBusy) {
                        LocalizedText("正在读取…", style = SaltTheme.textStyles.sub)
                    }
                }
                catalog.error?.let { ErrorBlock(it) }
                if (catalog.fetchedModels.isEmpty() && !catalog.actionBusy) {
                    EmptyState(
                        "未读取到模型",
                        catalog.actionMessage.ifBlank { "该端点可能不支持模型列表；可关闭后手动添加模型 ID。" }
                    )
                } else {
                    LazyColumn(
                        modifier = Modifier.weight(1f),
                        verticalArrangement = Arrangement.spacedBy(6.dp)
                    ) {
                        items(catalog.fetchedModels) { model ->
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clip(RoundedCornerShape(7.dp))
                                    .background(
                                        if (model in selected) SaltTheme.colors.highlight.copy(alpha = 0.1f)
                                        else SaltTheme.colors.subBackground
                                    )
                                    .clickable {
                                        selected = if (model in selected) selected - model else selected + model
                                    }
                                    .padding(11.dp),
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                LocalizedText(model, modifier = Modifier.weight(1f))
                                LocalizedText(
                                    if (model in selected) "已选择" else "未选择",
                                    style = SaltTheme.textStyles.sub,
                                    color = if (model in selected) SaltTheme.colors.highlight else SaltTheme.colors.subText
                                )
                            }
                        }
                    }
                }
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                    LocalizedButton(onClick = onClose, text = "取消", appearance = ButtonAppearance.Subtle)
                    Spacer(Modifier.width(8.dp))
                    LocalizedButton(
                        onClick = {
                            catalog.addFetchedModels(provider.name, selected.toList())
                            onClose()
                        },
                        text = "启用选中模型",
                        enabled = selected.isNotEmpty() && !catalog.actionBusy
                    )
                }
            }
        }
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun QuotaPanel(quota: kotlinx.serialization.json.JsonElement) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        listOf("status", "used", "limit", "remaining", "reset_at", "message").forEach { key ->
            val value = quota.objectOrEmpty().string(key)
            if (value.isNotBlank()) {
                StatusPill("$key: $value", SaltTheme.colors.highlight)
            }
        }
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun OAuthPanel(
    flow: kotlinx.serialization.json.JsonElement,
    providerName: String,
    controller: AppController
) {
    val obj = flow.objectOrEmpty()
    Row(
        modifier = Modifier.fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 8.dp)
            .clip(RoundedCornerShape(8.dp))
            .background(SaltTheme.colors.warning.copy(alpha = 0.08f))
            .padding(10.dp),
        horizontalArrangement = Arrangement.spacedBy(9.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Column(Modifier.weight(1f)) {
            LocalizedText("OAuth ${obj.string("status").ifBlank { "待授权" }}", fontWeight = FontWeight.Medium)
            LocalizedText(
                listOf(
                    obj.string("message"),
                    obj.string("verification_uri"),
                    obj.string("user_code")
                ).filter(String::isNotBlank).joinToString(" · "),
                style = SaltTheme.textStyles.sub,
                color = SaltTheme.colors.subText
            )
        }
        LocalizedButton(
            onClick = { controller.modelProviders.pollOAuth(providerName) },
            text = "检查授权",
            appearance = ButtonAppearance.Subtle
        )
    }
}

@Composable
private fun Field(label: String, content: @Composable () -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        LocalizedText(label, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
        content()
    }
}

private fun protocolText(provider: String): String = when (provider) {
    "openai_compatible" -> "OpenAI 兼容"
    "anthropic_compatible" -> "Anthropic 兼容"
    "ollama" -> "Ollama 原生"
    "mock" -> "离线演练"
    else -> provider.ifBlank { "协议未记录" }
}

private fun keySourceText(source: String): String = when (source) {
    "vault" -> "密钥已加密保存"
    "environment" -> "密钥来自环境变量"
    else -> "密钥未配置"
}

private fun formatContext(value: Long): String =
    if (value >= 1000) "${(value / 1000.0).toInt()}k" else value.toString()

private fun formatModelNumber(value: Double?): String =
    if (value == null) "" else if (value % 1.0 == 0.0) value.toInt().toString() else value.toString()
