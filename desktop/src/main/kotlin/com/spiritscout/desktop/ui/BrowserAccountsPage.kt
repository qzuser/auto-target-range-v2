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
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Add
import androidx.compose.material.icons.outlined.Delete
import androidx.compose.material.icons.outlined.Edit
import androidx.compose.material.icons.outlined.Lock
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.Save
import androidx.compose.material.icons.outlined.Window
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
import com.spiritscout.desktop.state.BrowserAccountRow

@OptIn(UnstableSaltUiApi::class)
@Composable
fun BrowserAccountsPage(controller: AppController) {
    val catalog = controller.browserAccounts
    var selected by remember { mutableStateOf("") }
    var adding by remember { mutableStateOf(false) }
    var editing by remember { mutableStateOf<BrowserAccountRow?>(null) }
    var clearConfirm by remember { mutableStateOf("") }
    var deleteConfirm by remember { mutableStateOf("") }
    LaunchedEffect(Unit) { catalog.refresh() }
    LaunchedEffect(catalog.accounts.map { it.id }) {
        if (catalog.accounts.none { it.id == selected }) selected = catalog.accounts.firstOrNull()?.id.orEmpty()
    }

    Column(Modifier.fillMaxSize().padding(24.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                LocalizedText("浏览器账号", style = SaltTheme.textStyles.largeTitle)
                LocalizedText(
                    "账号站点、登录态、保留策略与 MFA 分开管理；凭据只写入不回显。",
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
                text = "新建账号",
                leadingIcon = { Icon(Icons.Outlined.Add, null, modifier = Modifier.size(15.dp)) }
            )
        }
        catalog.error?.let { ErrorBlock(it) }
        if (catalog.message.isNotBlank()) {
            LocalizedText(catalog.message, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.success)
        }
        Row(Modifier.fillMaxSize(), horizontalArrangement = Arrangement.spacedBy(14.dp)) {
            Card(Modifier.width(430.dp).fillMaxHeight(), color = SaltTheme.colors.subBackground) {
                Column(Modifier.fillMaxSize()) {
                    Row(Modifier.fillMaxWidth().padding(15.dp), verticalAlignment = Alignment.CenterVertically) {
                        LocalizedText(
                            "${catalog.accounts.size} 个账号",
                            modifier = Modifier.weight(1f),
                            fontWeight = FontWeight.SemiBold
                        )
                        if (catalog.loading) {
                            LocalizedText("同步中…", style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
                        }
                    }
                    Box(Modifier.fillMaxWidth().height(1.dp).background(SaltTheme.colors.stroke))
                    if (catalog.accounts.isEmpty()) {
                        EmptyState("暂无浏览器账号", "添加账号站点后可打开独立登录浏览器并保存登录态。")
                    } else {
                        LazyColumn(
                            modifier = Modifier.fillMaxSize(),
                            contentPadding = androidx.compose.foundation.layout.PaddingValues(12.dp),
                            verticalArrangement = Arrangement.spacedBy(8.dp)
                        ) {
                            items(catalog.accounts, key = { it.id }) { account ->
                                BrowserAccountListRow(
                                    account,
                                    account.id == selected,
                                    onClick = { selected = account.id }
                                )
                            }
                        }
                    }
                }
            }
            Card(Modifier.weight(1f).fillMaxHeight(), color = SaltTheme.colors.subBackground) {
                val account = catalog.accounts.firstOrNull { it.id == selected }
                if (account == null) {
                    EmptyState("选择一个账号", "查看站点、登录态、TTL 和 MFA 配置。")
                } else {
                    Column(
                        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp),
                        verticalArrangement = Arrangement.spacedBy(12.dp)
                    ) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Box(
                                Modifier.size(44.dp).clip(RoundedCornerShape(9.dp))
                                    .background(SaltTheme.colors.highlight.copy(alpha = 0.12f)),
                                contentAlignment = Alignment.Center
                            ) {
                                Icon(Icons.Outlined.Lock, null, tint = SaltTheme.colors.highlight)
                            }
                            Spacer(Modifier.width(11.dp))
                            Column(Modifier.weight(1f)) {
                                LocalizedText(account.name, style = SaltTheme.textStyles.largeTitle)
                                LocalizedText(account.id, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
                            }
                            LocalizedButton(
                                onClick = { editing = account },
                                text = "编辑",
                                appearance = ButtonAppearance.Subtle,
                                leadingIcon = { Icon(Icons.Outlined.Edit, null, modifier = Modifier.size(15.dp)) }
                            )
                        }
                        LocalizedText(
                            account.role.ifBlank { "未填写身份说明" },
                            style = SaltTheme.textStyles.paragraph,
                            color = SaltTheme.colors.subText
                        )
                        account.origins.forEach { origin ->
                            LocalizedText(origin, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.highlight)
                        }
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            AccountMetric("保留策略", if (account.retain) "启用" else "关闭")
                            AccountMetric("TTL", "${account.ttlDays} 天")
                            AccountMetric("缓存", cacheText(account.cacheStatus))
                            AccountMetric("Cookie", account.cookieCount.toString())
                        }
                        LocalizedText(
                            "用户名提示：${account.usernameHint.ifBlank { "未配置" }} · " +
                                "凭据：${if (account.credentialsConfigured) "已配置" else "未配置"} · " +
                                "MFA：${mfaText(account.mfaMethod)}" +
                                account.mfaDestinationHint.takeIf(String::isNotBlank)?.let { "（$it）" }.orEmpty(),
                            style = SaltTheme.textStyles.sub,
                            color = SaltTheme.colors.subText
                        )
                        Box(Modifier.fillMaxWidth().height(1.dp).background(SaltTheme.colors.stroke))
                        Row(horizontalArrangement = Arrangement.spacedBy(7.dp)) {
                            LocalizedButton(
                                onClick = { catalog.action(account, "open") },
                                text = "打开登录",
                                appearance = ButtonAppearance.Subtle,
                                leadingIcon = { Icon(Icons.Outlined.Window, null, modifier = Modifier.size(15.dp)) }
                            )
                            LocalizedButton(
                                onClick = { catalog.action(account, "capture") },
                                text = "保存登录态",
                                appearance = ButtonAppearance.Subtle
                            )
                            LocalizedButton(
                                onClick = { catalog.action(account, "close") },
                                text = "关闭浏览器",
                                appearance = ButtonAppearance.Subtle
                            )
                        }
                        Row(horizontalArrangement = Arrangement.spacedBy(7.dp)) {
                            LocalizedButton(
                                onClick = {
                                    if (clearConfirm == account.id) {
                                        catalog.action(account, "clear")
                                        clearConfirm = ""
                                    } else {
                                        clearConfirm = account.id
                                    }
                                },
                                text = if (clearConfirm == account.id) "确认清理缓存" else "清理缓存",
                                appearance = ButtonAppearance.Subtle,
                                intent = ButtonIntent.Destructive
                            )
                            LocalizedButton(
                                onClick = {
                                    if (deleteConfirm == account.id) {
                                        catalog.action(account, "delete")
                                        deleteConfirm = ""
                                    } else {
                                        deleteConfirm = account.id
                                    }
                                },
                                text = if (deleteConfirm == account.id) "确认删除账号" else "删除账号",
                                appearance = ButtonAppearance.Subtle,
                                intent = ButtonIntent.Destructive,
                                leadingIcon = { Icon(Icons.Outlined.Delete, null, modifier = Modifier.size(15.dp)) }
                            )
                        }
                        LocalizedText(
                            "保存登录态不等于登录已验证；清除缓存不会删除账号配置。",
                            style = SaltTheme.textStyles.sub,
                            color = SaltTheme.colors.subText
                        )
                    }
                }
            }
        }
    }

    if (adding || editing != null) {
        BrowserAccountDialog(controller, editing) {
            adding = false
            editing = null
        }
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun BrowserAccountListRow(
    account: BrowserAccountRow,
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
            LocalizedText(account.name, modifier = Modifier.weight(1f), fontWeight = FontWeight.SemiBold)
            StatusPill(cacheText(account.cacheStatus), cacheColor(account.cacheStatus))
        }
        LocalizedText(
            account.role.ifBlank { account.origins.firstOrNull().orEmpty() },
            style = SaltTheme.textStyles.sub,
            color = SaltTheme.colors.subText,
            maxLines = 2
        )
        LocalizedText(
            "${account.originCount} 个站点 · ${account.cookieCount} Cookie · TTL ${account.ttlDays} 天",
            style = SaltTheme.textStyles.sub,
            color = SaltTheme.colors.subText
        )
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun BrowserAccountDialog(
    controller: AppController,
    account: BrowserAccountRow?,
    onClose: () -> Unit
) {
    val catalog = controller.browserAccounts
    var key by remember(account?.id) { mutableStateOf(account?.id.orEmpty()) }
    var name by remember(account?.id) { mutableStateOf(account?.name.orEmpty()) }
    var role by remember(account?.id) { mutableStateOf(account?.role.orEmpty()) }
    var origins by remember(account?.id) { mutableStateOf(account?.origins?.joinToString("\n").orEmpty()) }
    var retain by remember(account?.id) { mutableStateOf(account?.retain ?: true) }
    var ttl by remember(account?.id) { mutableStateOf((account?.ttlDays ?: 7).toString()) }
    var username by remember(account?.id) { mutableStateOf("") }
    var password by remember(account?.id) { mutableStateOf("") }
    var mfaMethod by remember(account?.id) { mutableStateOf(account?.mfaMethod ?: "none") }
    var mfaDestination by remember(account?.id) { mutableStateOf("") }
    var clearCredentials by remember(account?.id) { mutableStateOf(false) }

    LocalizedDialogWindow(
        onCloseRequest = onClose,
        title = if (account == null) "新建浏览器账号" else "编辑 ${account.name}",
        state = rememberDialogState(
            size = DpSize(760.dp, 780.dp),
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
                LocalizedText(
                    if (account == null) "新建浏览器账号" else "编辑 ${account.name}",
                    style = SaltTheme.textStyles.largeTitle
                )
                AccountField("账号标识") {
                    SpiritTextField(key, { key = it }, "字母、数字、下划线或短横线")
                }
                AccountField("名称") { SpiritTextField(name, { name = it }, "例如：测试账号 A") }
                AccountField("身份说明") { SpiritTextField(role, { role = it }, "账号角色、用途或限制") }
                AccountField("账号网站，每行一个") {
                    SpiritTextField(origins, { origins = it }, "https://example.com", singleLine = false)
                }
                Row(horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                    Box(Modifier.weight(1f)) {
                        AccountField("TTL（天）") { SpiritTextField(ttl, { ttl = it }, "7") }
                    }
                    Row(Modifier.weight(1f), verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            LocalizedText("保留登录态", fontWeight = FontWeight.Medium)
                            LocalizedText(
                                "关闭后不保存 Cookie/localStorage。",
                                style = SaltTheme.textStyles.sub,
                                color = SaltTheme.colors.subText
                            )
                        }
                        Switcher(state = retain, onChange = { retain = it })
                    }
                }
                AccountField("登录用户名（留空保持现有）") {
                    SpiritTextField(username, { username = it }, account?.usernameHint ?: "账号用户名")
                }
                AccountField("密码（留空保持现有）") {
                    SpiritPasswordField(password, { password = it }, "不回显现有密码")
                }
                AccountField("MFA 方式") {
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        listOf(
                            "none" to "无",
                            "sms" to "短信",
                            "email" to "邮箱",
                            "authenticator" to "动态码"
                        ).forEach { (value, label) ->
                            LocalizedButton(
                                onClick = { mfaMethod = value },
                                text = label,
                                appearance = if (mfaMethod == value) ButtonAppearance.Filled else ButtonAppearance.Subtle
                            )
                        }
                    }
                }
                AccountField("MFA 目标（留空保持现有）") {
                    SpiritTextField(mfaDestination, { mfaDestination = it }, "手机号或邮箱")
                }
                if (account?.credentialsConfigured == true) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            LocalizedText("清除已保存凭据", color = SaltTheme.colors.warning, fontWeight = FontWeight.Medium)
                            LocalizedText(
                                "勾选后保存会同时清除用户名、密码和登录态。",
                                style = SaltTheme.textStyles.sub,
                                color = SaltTheme.colors.subText
                            )
                        }
                        Switcher(state = clearCredentials, onChange = { clearCredentials = it })
                    }
                }
                catalog.error?.let {
                    LocalizedText(it, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.error)
                }
                Spacer(Modifier.height(8.dp))
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                    LocalizedButton(onClick = onClose, text = "取消", appearance = ButtonAppearance.Subtle)
                    Spacer(Modifier.width(8.dp))
                    LocalizedButton(
                        onClick = {
                            catalog.save(
                                original = account,
                                key = key,
                                name = name,
                                role = role,
                                originsText = origins,
                                retain = retain,
                                ttlDaysText = ttl,
                                username = username,
                                password = password,
                                mfaMethod = mfaMethod,
                                mfaDestination = mfaDestination,
                                clearCredentials = clearCredentials
                            )
                            onClose()
                        },
                        text = "保存账号",
                        enabled = !catalog.saving,
                        leadingIcon = { Icon(Icons.Outlined.Save, null, modifier = Modifier.size(15.dp)) }
                    )
                }
            }
        }
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun AccountMetric(label: String, value: String) {
    Row(
        modifier = Modifier
            .clip(RoundedCornerShape(8.dp))
            .background(SaltTheme.colors.background.copy(alpha = 0.5f))
            .padding(horizontal = 10.dp, vertical = 7.dp),
        horizontalArrangement = Arrangement.spacedBy(6.dp)
    ) {
        LocalizedText(label, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
        LocalizedText(value, style = SaltTheme.textStyles.sub, fontWeight = FontWeight.SemiBold)
    }
}

@Composable
private fun AccountField(label: String, content: @Composable () -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        LocalizedText(label, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
        content()
    }
}

private fun cacheText(value: String): String = when (value) {
    "available" -> "登录态可用"
    "expired" -> "登录态已过期"
    "empty" -> "未保存登录态"
    else -> value.ifBlank { "状态未知" }
}

@Composable
private fun cacheColor(value: String) = when (value) {
    "available" -> SaltTheme.colors.success
    "expired" -> SaltTheme.colors.warning
    else -> SaltTheme.colors.subText
}

private fun mfaText(value: String): String = when (value) {
    "sms" -> "短信验证码"
    "email" -> "邮箱验证码"
    "authenticator" -> "验证器动态码"
    else -> "无"
}
