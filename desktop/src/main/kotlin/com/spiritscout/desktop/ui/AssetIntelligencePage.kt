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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Lock
import androidx.compose.material.icons.outlined.Radar
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
import com.spiritscout.desktop.model.AssetProviderItem

@OptIn(UnstableSaltUiApi::class)
@Composable
fun AssetIntelligencePage(controller: AppController) {
    var editing by remember { mutableStateOf<AssetProviderItem?>(null) }
    LaunchedEffect(Unit) {
        controller.loadAssetProviders()
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(5.dp)) {
                LocalizedText("资产情报", style = SaltTheme.textStyles.largeTitle)
                LocalizedText(
                    "统一管理空间测绘与企业归属 Provider。外部结果先进入候选池，不等于授权、归属证明或可直接测试资产。",
                    style = SaltTheme.textStyles.sub,
                    color = SaltTheme.colors.subText
                )
            }
            LocalizedButton(
                onClick = controller::loadAssetProviders,
                text = "刷新",
                appearance = ButtonAppearance.Subtle,
                enabled = !controller.assetProvidersLoading,
                leadingIcon = { Icon(Icons.Outlined.Refresh, null, modifier = Modifier.size(15.dp)) }
            )
        }

        val ready = controller.assetProviders.count { it.enabled && it.keyConfigured }
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            ProviderSummary("$ready 个 Provider 就绪")
            ProviderSummary("${controller.assetProviders.size} 个来源")
            ProviderSummary("凭据不回显、不进入普通日志")
        }

        controller.assetProvidersError?.let {
            ErrorBlock(it)
        }

        if (controller.assetProvidersLoading && controller.assetProviders.isEmpty()) {
            LoadingBlock("正在读取 Provider…")
        } else if (controller.assetProviders.isEmpty()) {
            EmptyState("暂无资产情报 Provider", "后端没有返回空间测绘或企业归属 Provider。")
        } else {
            ProviderGroup(
                title = "网络空间测绘",
                subtitle = "只保留明确授权范围内的候选，并在进入测试前再次核验。",
                providers = controller.assetProviders.filter { it.category == "cyberspace" },
                onEdit = { editing = it }
            )
            ProviderGroup(
                title = "企业归属与备案",
                subtitle = "仅组织线索任务可运行；Cookie 只加密保存在 Vault。",
                providers = controller.assetProviders.filter { it.category == "enterprise" },
                onEdit = { editing = it }
            )
            CandidateRules()
        }
    }

    editing?.let { provider ->
        ProviderDialog(
            controller = controller,
            provider = provider,
            onClose = { editing = null }
        )
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun CandidateRules() {
    Card(Modifier.fillMaxWidth(), color = SaltTheme.colors.subBackground) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(11.dp)
        ) {
            LocalizedText("候选准入规则", fontWeight = FontWeight.SemiBold)
            LocalizedText(
                "发现来源与测试授权严格分离。",
                style = SaltTheme.textStyles.sub,
                color = SaltTheme.colors.subText
            )
            listOf(
                "明确 URL、域名或子域名" to
                    "采用封闭范围，只测试用户逐项提供的目标；测绘结果不得扩散到同公司或其他域名。",
                "通配符子域" to
                    "FOFA、Hunter、Quake、ZoomEye 与 CT 只补充该后缀下的具体子域，根域不自动进入范围。",
                "公司、省份与控股线索" to
                    "未给出确定域名时，爱企查、企查查等原生 Provider 可按企业、地区、分支、投资和控股比例生成候选并保留归属证据。",
                "核验后再晋级" to
                    "企业 Cookie 和 API Key 只加密保存在 Vault；候选仍需归属、DNS 与 HTTP 核验。"
            ).forEachIndexed { index, (title, detail) ->
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    StatusPill((index + 1).toString(), SaltTheme.colors.highlight)
                    Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
                        LocalizedText(title, fontWeight = FontWeight.Medium)
                        LocalizedText(
                            detail,
                            style = SaltTheme.textStyles.sub,
                            color = SaltTheme.colors.subText
                        )
                    }
                }
            }
        }
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun ProviderGroup(
    title: String,
    subtitle: String,
    providers: List<AssetProviderItem>,
    onEdit: (AssetProviderItem) -> Unit
) {
    Column(verticalArrangement = Arrangement.spacedBy(9.dp)) {
        Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
            LocalizedText(title, fontWeight = FontWeight.SemiBold)
            LocalizedText(subtitle, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
        }
        if (providers.isEmpty()) {
            LocalizedText(
                "该分类没有 Provider。",
                style = SaltTheme.textStyles.sub,
                color = SaltTheme.colors.subText
            )
        } else {
            providers.forEach { provider ->
                ProviderRow(provider, onEdit)
            }
        }
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun ProviderRow(provider: AssetProviderItem, onEdit: (AssetProviderItem) -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(SaltTheme.colors.subBackground)
            .padding(15.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(13.dp)
    ) {
        Box(
            modifier = Modifier
                .size(36.dp)
                .clip(RoundedCornerShape(8.dp))
                .background(SaltTheme.colors.highlight.copy(alpha = 0.12f)),
            contentAlignment = Alignment.Center
        ) {
            Icon(
                if (provider.category == "enterprise") Icons.Outlined.Lock else Icons.Outlined.Radar,
                null,
                modifier = Modifier.size(18.dp),
                tint = SaltTheme.colors.highlight
            )
        }
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                LocalizedText(provider.name, fontWeight = FontWeight.SemiBold)
                ProviderState(provider)
            }
            LocalizedText(
                providerDescription(provider),
                style = SaltTheme.textStyles.sub,
                color = SaltTheme.colors.subText
            )
            LocalizedText(
                "凭据来源：${providerSource(provider.keySource)} · " +
                    if (provider.enabled) "自动候选已开启" else "自动候选已关闭",
                style = SaltTheme.textStyles.sub,
                color = SaltTheme.colors.subText
            )
        }
        LocalizedButton(
            onClick = { onEdit(provider) },
            text = "配置 Provider",
            appearance = ButtonAppearance.Subtle,
            leadingIcon = { Icon(Icons.Outlined.Settings, null, modifier = Modifier.size(15.dp)) }
        )
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun ProviderState(provider: AssetProviderItem) {
    val color = when {
        provider.enabled && provider.keyConfigured -> SaltTheme.colors.success
        provider.enabled -> SaltTheme.colors.warning
        else -> SaltTheme.colors.subText
    }
    val label = when {
        !provider.enabled -> "未启用"
        provider.keyConfigured -> "已就绪"
        else -> "待配置"
    }
    StatusPill(label, color)
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun ProviderSummary(text: String) {
    Box(
        modifier = Modifier
            .clip(RoundedCornerShape(8.dp))
            .background(SaltTheme.colors.subBackground)
            .padding(horizontal = 11.dp, vertical = 7.dp)
    ) {
        LocalizedText(text, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun ProviderDialog(
    controller: AppController,
    provider: AssetProviderItem,
    onClose: () -> Unit
) {
    var enabled by remember(provider.provider) { mutableStateOf(provider.enabled) }
    var email by remember(provider.provider) { mutableStateOf("") }
    var apiKey by remember(provider.provider) { mutableStateOf("") }
    var cookie by remember(provider.provider) { mutableStateOf("") }
    var confirmClear by remember(provider.provider) { mutableStateOf(false) }

    LocalizedDialogWindow(
        onCloseRequest = onClose,
        title = "配置 ${provider.name}",
        state = rememberDialogState(
            size = DpSize(620.dp, 620.dp),
            position = WindowPosition.Aligned(Alignment.Center)
        ),
        resizable = false
    ) {
        SaltTheme(configs = SaltConfigs.default(isDarkTheme = controller.darkTheme)) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .background(SaltTheme.colors.background)
                    .padding(24.dp),
                verticalArrangement = Arrangement.spacedBy(14.dp)
            ) {
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    LocalizedText(provider.name, style = SaltTheme.textStyles.largeTitle)
                    LocalizedText(
                        providerDescription(provider),
                        style = SaltTheme.textStyles.sub,
                        color = SaltTheme.colors.subText
                    )
                }
                Card(Modifier.fillMaxWidth(), color = SaltTheme.colors.subBackground) {
                    Column(Modifier.padding(15.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Column(Modifier.weight(1f)) {
                                LocalizedText(
                                    if (provider.category == "enterprise") "启用企业资产收集" else "启用候选检索",
                                    fontWeight = FontWeight.Medium
                                )
                                LocalizedText(
                                    "关闭后不会自动生成该来源的候选。",
                                    style = SaltTheme.textStyles.sub,
                                    color = SaltTheme.colors.subText
                                )
                            }
                            Switcher(state = enabled, onChange = { enabled = it })
                        }
                        if (provider.provider == "fofa") {
                            Column(verticalArrangement = Arrangement.spacedBy(7.dp)) {
                                LocalizedText("FOFA 邮箱", style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
                                SpiritTextField(email, { email = it }, "name@example.com")
                            }
                            Column(verticalArrangement = Arrangement.spacedBy(7.dp)) {
                                LocalizedText("FOFA API Key", style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
                                SpiritPasswordField(apiKey, { apiKey = it }, "不回显现有密钥")
                            }
                        } else if (provider.category == "enterprise") {
                            Column(verticalArrangement = Arrangement.spacedBy(7.dp)) {
                                LocalizedText("Cookie", style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
                                SpiritTextField(
                                    cookie,
                                    { cookie = it },
                                    "Cookie: ...",
                                    singleLine = false
                                )
                            }
                        } else {
                            Column(verticalArrangement = Arrangement.spacedBy(7.dp)) {
                                LocalizedText("API Key", style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
                                SpiritPasswordField(apiKey, { apiKey = it }, "不回显现有密钥")
                            }
                        }
                    }
                }
                LocalizedText(
                    "凭据不会回显。留空表示保持已保存凭据不变；清除凭据会同时停用该 Provider。",
                    style = SaltTheme.textStyles.sub,
                    color = SaltTheme.colors.subText
                )
                controller.assetProvidersError?.let {
                    LocalizedText(it, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.error)
                }
                if (confirmClear) {
                    LocalizedText(
                        "确认清除 ${provider.name} 的加密凭据并停用自动候选？",
                        color = SaltTheme.colors.warning,
                        fontWeight = FontWeight.Medium
                    )
                }
                Spacer(Modifier.weight(1f))
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    LocalizedButton(
                        onClick = {
                            if (confirmClear) {
                                controller.clearAssetProviderCredentials(
                                    provider.provider,
                                    provider.version
                                )
                                onClose()
                            } else {
                                confirmClear = true
                            }
                        },
                        text = if (confirmClear) "确认清除" else "清除凭据",
                        appearance = ButtonAppearance.Subtle,
                        intent = ButtonIntent.Destructive,
                        enabled = provider.storedCredentials && !controller.assetProvidersLoading
                    )
                    Spacer(Modifier.weight(1f))
                    LocalizedButton(
                        onClick = onClose,
                        text = "取消",
                        appearance = ButtonAppearance.Subtle
                    )
                    LocalizedButton(
                        onClick = {
                            controller.saveAssetProvider(
                                provider = provider.provider,
                                enabled = enabled,
                                version = provider.version,
                                email = email,
                                apiKey = apiKey,
                                cookie = cookie
                            )
                            onClose()
                        },
                        text = "保存配置",
                        enabled = !controller.assetProvidersLoading
                    )
                }
            }
        }
    }
}

private fun providerDescription(provider: AssetProviderItem): String =
    if (provider.category == "enterprise") {
        "采集企业基本信息、ICP 备案、分支和投资关系；只为组织线索任务生成候选。"
    } else {
        "被动检索已授权域名或通配符后缀，结果必须再次做范围过滤与存活核验。"
    }

private fun providerSource(value: String): String = when (value) {
    "saved" -> "加密资源库"
    "environment" -> "环境变量"
    "none", "" -> "未配置"
    else -> value
}
