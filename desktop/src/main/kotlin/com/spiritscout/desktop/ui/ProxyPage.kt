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
import androidx.compose.material.icons.outlined.Link
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.Speed
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
import com.spiritscout.desktop.state.ProxyNodeRow
import com.spiritscout.desktop.state.ProxyPlanRow
import com.spiritscout.desktop.state.ProxySubscriptionRow

@OptIn(UnstableSaltUiApi::class)
@Composable
fun ProxyPage(controller: AppController) {
    val catalog = controller.proxyPool
    var showImport by remember { mutableStateOf(false) }
    var showSubscribe by remember { mutableStateOf(false) }
    var showPlan by remember { mutableStateOf(false) }
    var deleteConfirm by remember { mutableStateOf("") }
    LaunchedEffect(Unit) { catalog.refresh() }

    Column(Modifier.fillMaxSize().padding(24.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                LocalizedText("代理池", style = SaltTheme.textStyles.largeTitle)
                LocalizedText(
                    "管理节点、订阅和固定出口方案。任务启动后锁定方案，不在运行中热切换。",
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
                onClick = { showImport = true },
                text = "导入节点",
                leadingIcon = { Icon(Icons.Outlined.Download, null, modifier = Modifier.size(15.dp)) }
            )
            Spacer(Modifier.width(8.dp))
            LocalizedButton(
                onClick = { showSubscribe = true },
                text = "添加订阅",
                appearance = ButtonAppearance.Subtle,
                leadingIcon = { Icon(Icons.Outlined.Link, null, modifier = Modifier.size(15.dp)) }
            )
            Spacer(Modifier.width(8.dp))
            LocalizedButton(
                onClick = { showPlan = true },
                text = "新建出口方案",
                appearance = ButtonAppearance.Subtle,
                leadingIcon = { Icon(Icons.Outlined.Add, null, modifier = Modifier.size(15.dp)) }
            )
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            ProxySummary("节点", catalog.nodes.size.toString())
            ProxySummary("方案", catalog.plans.size.toString())
            ProxySummary("订阅", catalog.subscriptions.size.toString())
            ProxySummary("Mihomo", if (catalog.mihomoAvailable) "可用" else "未检测到")
        }
        catalog.error?.let { ErrorBlock(it) }
        if (catalog.message.isNotBlank()) {
            LocalizedText(catalog.message, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.success)
        }
        Row(Modifier.fillMaxSize(), horizontalArrangement = Arrangement.spacedBy(14.dp)) {
            Card(Modifier.weight(1.35f).fillMaxHeight(), color = SaltTheme.colors.subBackground) {
                Column(Modifier.fillMaxSize()) {
                    LocalizedText("节点", modifier = Modifier.padding(15.dp), fontWeight = FontWeight.SemiBold)
                    Box(Modifier.fillMaxWidth().height(1.dp).background(SaltTheme.colors.stroke))
                    if (catalog.nodes.isEmpty()) {
                        EmptyState("暂无代理节点", "导入 Clash/Mihomo 节点配置，或添加订阅。")
                    } else {
                        LazyColumn(
                            modifier = Modifier.fillMaxSize(),
                            contentPadding = androidx.compose.foundation.layout.PaddingValues(12.dp),
                            verticalArrangement = Arrangement.spacedBy(7.dp)
                        ) {
                            items(catalog.nodes, key = { it.id }) { node ->
                                ProxyNodeCard(
                                    node = node,
                                    onBenchmark = { catalog.benchmark(listOf(node.id)) },
                                    deleteConfirm = deleteConfirm == "node:${node.id}",
                                    onDelete = {
                                        if (deleteConfirm == "node:${node.id}") {
                                            catalog.delete("node", node.id)
                                            deleteConfirm = ""
                                        } else {
                                            deleteConfirm = "node:${node.id}"
                                        }
                                    }
                                )
                            }
                        }
                    }
                }
            }
            Column(Modifier.weight(1f).fillMaxHeight(), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Card(Modifier.fillMaxWidth().weight(1f), color = SaltTheme.colors.subBackground) {
                    Column(Modifier.fillMaxSize()) {
                        LocalizedText("出口方案", modifier = Modifier.padding(15.dp), fontWeight = FontWeight.SemiBold)
                        Box(Modifier.fillMaxWidth().height(1.dp).background(SaltTheme.colors.stroke))
                        if (catalog.plans.isEmpty()) {
                            EmptyState("暂无方案", "选择 1–8 个节点创建固定出口方案。")
                        } else {
                            LazyColumn(
                                modifier = Modifier.fillMaxSize(),
                                contentPadding = androidx.compose.foundation.layout.PaddingValues(12.dp),
                                verticalArrangement = Arrangement.spacedBy(7.dp)
                            ) {
                                items(catalog.plans, key = { it.id }) { plan ->
                                    ProxyPlanCard(
                                        plan = plan,
                                        nodeNames = plan.nodes.mapNotNull { id ->
                                            catalog.nodes.firstOrNull { it.id == id }?.name
                                        },
                                        onBenchmark = { catalog.benchmark(plan.nodes) },
                                        deleteConfirm = deleteConfirm == "plan:${plan.id}",
                                        onDelete = {
                                            if (deleteConfirm == "plan:${plan.id}") {
                                                catalog.delete("plan", plan.id)
                                                deleteConfirm = ""
                                            } else {
                                                deleteConfirm = "plan:${plan.id}"
                                            }
                                        }
                                    )
                                }
                            }
                        }
                    }
                }
                Card(Modifier.fillMaxWidth().heightIn(max = 300.dp), color = SaltTheme.colors.subBackground) {
                    Column(Modifier.fillMaxSize()) {
                        LocalizedText("订阅", modifier = Modifier.padding(15.dp), fontWeight = FontWeight.SemiBold)
                        Box(Modifier.fillMaxWidth().height(1.dp).background(SaltTheme.colors.stroke))
                        if (catalog.subscriptions.isEmpty()) {
                            EmptyState("暂无订阅", "添加 Mihomo 兼容订阅链接。")
                        } else {
                            LazyColumn(
                                modifier = Modifier.fillMaxSize(),
                                contentPadding = androidx.compose.foundation.layout.PaddingValues(12.dp),
                                verticalArrangement = Arrangement.spacedBy(7.dp)
                            ) {
                                items(catalog.subscriptions, key = { it.id }) { subscription ->
                                    ProxySubscriptionCard(
                                        subscription,
                                        onRefresh = { catalog.refreshSubscription(subscription.id) },
                                        deleteConfirm = deleteConfirm == "subscription:${subscription.id}",
                                        onDelete = {
                                            if (deleteConfirm == "subscription:${subscription.id}") {
                                                catalog.delete("subscription", subscription.id)
                                                deleteConfirm = ""
                                            } else {
                                                deleteConfirm = "subscription:${subscription.id}"
                                            }
                                        }
                                    )
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    if (showImport) ProxyImportDialog(controller) { showImport = false }
    if (showSubscribe) ProxySubscribeDialog(controller) { showSubscribe = false }
    if (showPlan) ProxyPlanDialog(controller) { showPlan = false }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun ProxyNodeCard(
    node: ProxyNodeRow,
    onBenchmark: () -> Unit,
    deleteConfirm: Boolean,
    onDelete: () -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(SaltTheme.colors.background.copy(alpha = 0.5f))
            .padding(11.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(9.dp)
    ) {
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
            Row(horizontalArrangement = Arrangement.spacedBy(7.dp), verticalAlignment = Alignment.CenterVertically) {
                LocalizedText(node.name, fontWeight = FontWeight.Medium)
                StatusPill(node.type.ifBlank { "节点" }, SaltTheme.colors.highlight)
                if (!node.selectable) StatusPill("非代理提示", SaltTheme.colors.warning)
            }
            LocalizedText(
                "${node.server}:${node.port} · ${node.kind} · TLS ${node.tlsVerification}",
                style = SaltTheme.textStyles.sub,
                color = SaltTheme.colors.subText
            )
            benchmarkText(node)?.let {
                LocalizedText(it, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.success)
            }
        }
        LocalizedButton(
            onClick = onBenchmark,
            text = "测速",
            appearance = ButtonAppearance.Subtle,
            enabled = node.selectable,
            leadingIcon = { Icon(Icons.Outlined.Speed, null, modifier = Modifier.size(14.dp)) }
        )
        LocalizedButton(
            onClick = onDelete,
            text = if (deleteConfirm) "确认" else "删除",
            appearance = ButtonAppearance.Subtle,
            intent = ButtonIntent.Destructive
        )
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun ProxyPlanCard(
    plan: ProxyPlanRow,
    nodeNames: List<String>,
    onBenchmark: () -> Unit,
    deleteConfirm: Boolean,
    onDelete: () -> Unit
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(SaltTheme.colors.background.copy(alpha = 0.5f))
            .padding(11.dp),
        verticalArrangement = Arrangement.spacedBy(5.dp)
    ) {
        LocalizedText(plan.name, fontWeight = FontWeight.Medium)
        LocalizedText(
            nodeNames.ifEmpty { plan.nodes }.joinToString(" → "),
            style = SaltTheme.textStyles.sub,
            color = SaltTheme.colors.subText
        )
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            LocalizedButton(
                onClick = onBenchmark,
                text = "方案测速",
                appearance = ButtonAppearance.Subtle,
                leadingIcon = { Icon(Icons.Outlined.Speed, null, modifier = Modifier.size(14.dp)) }
            )
            LocalizedButton(
                onClick = onDelete,
                text = if (deleteConfirm) "确认删除" else "删除",
                appearance = ButtonAppearance.Subtle,
                intent = ButtonIntent.Destructive
            )
        }
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun ProxySubscriptionCard(
    subscription: ProxySubscriptionRow,
    onRefresh: () -> Unit,
    deleteConfirm: Boolean,
    onDelete: () -> Unit
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(SaltTheme.colors.background.copy(alpha = 0.5f))
            .padding(10.dp),
        verticalArrangement = Arrangement.spacedBy(4.dp)
    ) {
        LocalizedText(subscription.name, fontWeight = FontWeight.Medium)
        LocalizedText(
            "${subscription.nodeCount} 个节点 · ${subscription.noticeCount} 个提示",
            style = SaltTheme.textStyles.sub,
            color = SaltTheme.colors.subText
        )
        subscription.diagnostic.takeIf(String::isNotBlank)?.let {
            LocalizedText(it, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.warning)
        }
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            LocalizedButton(
                onClick = onRefresh,
                text = "刷新",
                appearance = ButtonAppearance.Subtle,
                leadingIcon = { Icon(Icons.Outlined.Refresh, null, modifier = Modifier.size(14.dp)) }
            )
            LocalizedButton(
                onClick = onDelete,
                text = if (deleteConfirm) "确认删除" else "删除",
                appearance = ButtonAppearance.Subtle,
                intent = ButtonIntent.Destructive
            )
        }
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun ProxyImportDialog(controller: AppController, onClose: () -> Unit) {
    var content by remember { mutableStateOf("") }
    LocalizedDialogWindow(
        onCloseRequest = onClose,
        title = "导入代理节点",
        state = rememberDialogState(
            size = DpSize(700.dp, 640.dp),
            position = WindowPosition.Aligned(Alignment.Center)
        ),
        resizable = false
    ) {
        SaltTheme(configs = SaltConfigs.default(isDarkTheme = controller.darkTheme)) {
            Column(
                Modifier.fillMaxSize().background(SaltTheme.colors.background).padding(22.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                LocalizedText("导入 Clash / Mihomo 节点", style = SaltTheme.textStyles.largeTitle)
                LocalizedText(
                    "只接受内联 proxies；不加载远程 provider、脚本、TUN 或外部控制器。",
                    style = SaltTheme.textStyles.sub,
                    color = SaltTheme.colors.subText
                )
                SpiritTextField(content, { content = it }, "粘贴 Mihomo YAML 或节点 URI…", singleLine = false)
                controller.proxyPool.error?.let {
                    LocalizedText(it, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.error)
                }
                Spacer(Modifier.weight(1f))
                DialogActions(
                    onCancel = onClose,
                    onConfirm = {
                        controller.proxyPool.importNodes(content)
                        onClose()
                    },
                    confirmText = "导入节点",
                    enabled = !controller.proxyPool.actionBusy && content.isNotBlank()
                )
            }
        }
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun ProxySubscribeDialog(controller: AppController, onClose: () -> Unit) {
    var name by remember { mutableStateOf("") }
    var url by remember { mutableStateOf("") }
    LocalizedDialogWindow(
        onCloseRequest = onClose,
        title = "添加代理订阅",
        state = rememberDialogState(
            size = DpSize(620.dp, 430.dp),
            position = WindowPosition.Aligned(Alignment.Center)
        ),
        resizable = false
    ) {
        SaltTheme(configs = SaltConfigs.default(isDarkTheme = controller.darkTheme)) {
            Column(
                Modifier.fillMaxSize().background(SaltTheme.colors.background).padding(22.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                LocalizedText("添加代理订阅", style = SaltTheme.textStyles.largeTitle)
                ProxyField("名称") { SpiritTextField(name, { name = it }, "例如：主力订阅") }
                ProxyField("订阅地址") { SpiritTextField(url, { url = it }, "https://example.com/subscription") }
                LocalizedText(
                    "订阅内容会在后端解析并保存为内联节点，订阅 URL 不会回显到日志。",
                    style = SaltTheme.textStyles.sub,
                    color = SaltTheme.colors.subText
                )
                controller.proxyPool.error?.let {
                    LocalizedText(it, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.error)
                }
                Spacer(Modifier.weight(1f))
                DialogActions(
                    onCancel = onClose,
                    onConfirm = {
                        controller.proxyPool.subscribe(name, url)
                        onClose()
                    },
                    confirmText = "添加订阅",
                    enabled = !controller.proxyPool.actionBusy && name.isNotBlank() && url.isNotBlank()
                )
            }
        }
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun ProxyPlanDialog(controller: AppController, onClose: () -> Unit) {
    var name by remember { mutableStateOf("") }
    var selected by remember { mutableStateOf(setOf<String>()) }
    LocalizedDialogWindow(
        onCloseRequest = onClose,
        title = "新建出口方案",
        state = rememberDialogState(
            size = DpSize(680.dp, 640.dp),
            position = WindowPosition.Aligned(Alignment.Center)
        ),
        resizable = false
    ) {
        SaltTheme(configs = SaltConfigs.default(isDarkTheme = controller.darkTheme)) {
            Column(
                Modifier.fillMaxSize().background(SaltTheme.colors.background).padding(22.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                LocalizedText("新建固定出口方案", style = SaltTheme.textStyles.largeTitle)
                LocalizedText(
                    "按顺序选择 1–8 个节点；任务启动后锁定该方案的出口快照。",
                    style = SaltTheme.textStyles.sub,
                    color = SaltTheme.colors.subText
                )
                ProxyField("方案名称") { SpiritTextField(name, { name = it }, "例如：上海出口") }
                LazyColumn(
                    modifier = Modifier.weight(1f),
                    verticalArrangement = Arrangement.spacedBy(6.dp)
                ) {
                    items(controller.proxyPool.nodes.filter { it.selectable }, key = { it.id }) { node ->
                        val checked = node.id in selected
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clip(RoundedCornerShape(7.dp))
                                .background(
                                    if (checked) SaltTheme.colors.highlight.copy(alpha = 0.1f)
                                    else SaltTheme.colors.subBackground
                                )
                                .clickable {
                                    selected = if (checked) selected - node.id else selected + node.id
                                }
                                .padding(10.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            LocalizedText(node.name, modifier = Modifier.weight(1f))
                            LocalizedText(
                                "${node.server}:${node.port}",
                                style = SaltTheme.textStyles.sub,
                                color = SaltTheme.colors.subText
                            )
                            if (checked) {
                                Spacer(Modifier.width(8.dp))
                                StatusPill("已选", SaltTheme.colors.highlight)
                            }
                        }
                    }
                }
                controller.proxyPool.error?.let {
                    LocalizedText(it, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.error)
                }
                DialogActions(
                    onCancel = onClose,
                    onConfirm = {
                        controller.proxyPool.createPlan(name, selected.toList())
                        onClose()
                    },
                    confirmText = "创建方案",
                    enabled = !controller.proxyPool.actionBusy && name.isNotBlank() && selected.isNotEmpty()
                )
            }
        }
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun DialogActions(
    onCancel: () -> Unit,
    onConfirm: () -> Unit,
    confirmText: String,
    enabled: Boolean
) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
        LocalizedButton(onClick = onCancel, text = "取消", appearance = ButtonAppearance.Subtle)
        Spacer(Modifier.width(8.dp))
        LocalizedButton(onClick = onConfirm, text = confirmText, enabled = enabled)
    }
}

@Composable
private fun ProxyField(label: String, content: @Composable () -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        LocalizedText(label, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
        content()
    }
}

@Composable
private fun ProxySummary(label: String, value: String) {
    Row(
        modifier = Modifier
            .clip(RoundedCornerShape(8.dp))
            .background(SaltTheme.colors.subBackground)
            .padding(horizontal = 11.dp, vertical = 7.dp),
        horizontalArrangement = Arrangement.spacedBy(6.dp)
    ) {
        LocalizedText(label, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
        LocalizedText(value, style = SaltTheme.textStyles.sub, fontWeight = FontWeight.SemiBold)
    }
}

private fun benchmarkText(node: ProxyNodeRow): String? {
    val benchmark = node.benchmark ?: return null
    val text = benchmark.toString()
    return if (text.contains("latency")) text.trim('"') else "已有测速结果"
}
