package com.spiritscout.desktop.ui

import androidx.compose.foundation.background
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
import androidx.compose.material.icons.outlined.PauseCircle
import androidx.compose.material.icons.outlined.PlayArrow
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.StopCircle
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
import com.spiritscout.desktop.state.AssetCampaignRow
import com.spiritscout.desktop.state.AssetTargetRow
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive

@OptIn(UnstableSaltUiApi::class)
@Composable
fun AssetCollectionPage(controller: AppController) {
    val collection = controller.assetCollection
    var showCreate by remember { mutableStateOf(false) }
    var deleteConfirm by remember { mutableStateOf("") }
    LaunchedEffect(Unit) {
        collection.open()
        while (isActive) {
            delay(5_000)
            if (!collection.loading && !collection.actionBusy) collection.refresh()
        }
    }

    Column(Modifier.fillMaxSize().padding(24.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                LocalizedText("资产收集", style = SaltTheme.textStyles.largeTitle)
                LocalizedText(
                    "AI 根据目标和项目规则选择收集命令；候选资产只有经用户勾选后才可交接给 SRC 会话。",
                    style = SaltTheme.textStyles.sub,
                    color = SaltTheme.colors.subText
                )
            }
            LocalizedButton(
                onClick = collection::refresh,
                text = "刷新",
                appearance = ButtonAppearance.Subtle,
                leadingIcon = { Icon(Icons.Outlined.Refresh, null, modifier = Modifier.size(15.dp)) }
            )
            Spacer(Modifier.width(8.dp))
            LocalizedButton(
                onClick = { showCreate = true },
                text = "新建收集任务",
                enabled = collection.selectedProjectId.isNotBlank() &&
                    collection.selectedModel.isNotBlank() &&
                    !collection.actionBusy,
                leadingIcon = { Icon(Icons.Outlined.Add, null, modifier = Modifier.size(16.dp)) }
            )
        }

        CollectionSelectors(controller)
        collection.error?.let { ErrorBlock(it) }

        Row(
            modifier = Modifier.fillMaxSize(),
            horizontalArrangement = Arrangement.spacedBy(14.dp)
        ) {
            Card(Modifier.width(430.dp).fillMaxHeight(), color = SaltTheme.colors.subBackground) {
                Column(Modifier.fillMaxSize()) {
                    Row(
                        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        LocalizedText(
                            "${collection.campaigns.size} 个收集批次",
                            modifier = Modifier.weight(1f),
                            fontWeight = FontWeight.SemiBold
                        )
                        if (collection.loading) {
                            LocalizedText("同步中…", style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
                        }
                    }
                    Box(Modifier.fillMaxWidth().height(1.dp).background(SaltTheme.colors.stroke))
                    if (collection.campaigns.isEmpty()) {
                        EmptyState(
                            "当前项目暂无收集批次",
                            "选择项目和模型后，点击「新建收集任务」。"
                        )
                    } else {
                        LazyColumn(
                            modifier = Modifier.fillMaxSize(),
                            contentPadding = androidx.compose.foundation.layout.PaddingValues(12.dp),
                            verticalArrangement = Arrangement.spacedBy(8.dp)
                        ) {
                            items(collection.campaigns, key = { it.id }) { campaign ->
                                CampaignRow(
                                    campaign = campaign,
                                    selected = collection.selectedCampaignId == campaign.id,
                                    deleteConfirm = deleteConfirm == campaign.id,
                                    onSelect = { collection.selectCampaign(campaign.id) },
                                    onAction = { collection.campaignAction(campaign.id, it) },
                                    onDelete = {
                                        if (deleteConfirm == campaign.id) {
                                            collection.deleteCampaign(campaign.id)
                                            deleteConfirm = ""
                                        } else {
                                            deleteConfirm = campaign.id
                                        }
                                    }
                                )
                            }
                        }
                    }
                }
            }
            Card(Modifier.weight(1f).fillMaxHeight(), color = SaltTheme.colors.subBackground) {
                CampaignDetail(controller, deleteConfirm) { deleteConfirm = it }
            }
        }
    }

    if (showCreate) {
        CreateCampaignDialog(controller) { showCreate = false }
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun CollectionSelectors(controller: AppController) {
    val collection = controller.assetCollection
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            LocalizedText("项目", style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText, modifier = Modifier.width(48.dp))
            LazyRow(modifier = Modifier.weight(1f), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                items(collection.projects, key = { it.id }) { project ->
                    LocalizedButton(
                        onClick = { collection.selectProject(project.id) },
                        text = project.label,
                        appearance = if (collection.selectedProjectId == project.id) {
                            ButtonAppearance.Filled
                        } else {
                            ButtonAppearance.Subtle
                        }
                    )
                }
            }
        }
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            LocalizedText("模型", style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText, modifier = Modifier.width(48.dp))
            LazyRow(modifier = Modifier.weight(1f), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                items(collection.models, key = { it.id }) { model ->
                    LocalizedButton(
                        onClick = { collection.selectModel(model.id) },
                        text = model.label,
                        appearance = if (collection.selectedModel == model.id) {
                            ButtonAppearance.Filled
                        } else {
                            ButtonAppearance.Subtle
                        }
                    )
                }
            }
        }
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            LocalizedText("出口", style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText, modifier = Modifier.width(48.dp))
            LazyRow(modifier = Modifier.weight(1f), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                item {
                    LocalizedButton(
                        onClick = { collection.selectProxyPlan("direct") },
                        text = "直连",
                        appearance = if (collection.selectedProxyPlanId == "direct") {
                            ButtonAppearance.Filled
                        } else {
                            ButtonAppearance.Subtle
                        }
                    )
                }
                items(collection.proxyPlans, key = { it.id }) { plan ->
                    LocalizedButton(
                        onClick = { collection.selectProxyPlan(plan.id) },
                        text = plan.label,
                        appearance = if (collection.selectedProxyPlanId == plan.id) {
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

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun CampaignRow(
    campaign: AssetCampaignRow,
    selected: Boolean,
    deleteConfirm: Boolean,
    onSelect: () -> Unit,
    onAction: (String) -> Unit,
    onDelete: () -> Unit
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(
                if (selected) SaltTheme.colors.highlight.copy(alpha = 0.11f)
                else SaltTheme.colors.background.copy(alpha = 0.5f)
            )
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(7.dp)
    ) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            LocalizedText(
                campaign.targets.joinToString("、").ifBlank { "资产收集任务" },
                modifier = Modifier.weight(1f),
                fontWeight = FontWeight.Medium,
                maxLines = 2
            )
            StatusPill(statusText(campaign.status), collectionStatusColor(campaign.status))
        }
        LocalizedText(
            "${campaign.id} · LLM ${campaign.model.ifBlank { "历史未记录" }}",
            style = SaltTheme.textStyles.sub,
            color = SaltTheme.colors.subText
        )
        LocalizedText(
            "${campaign.commands} 次命令/工具调用 · ${campaign.candidates} 个资产",
            style = SaltTheme.textStyles.sub,
            color = SaltTheme.colors.subText
        )
        campaign.error.takeIf(String::isNotBlank)?.let {
            LocalizedText(it, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.error, maxLines = 2)
        }
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            LocalizedButton(
                onClick = onSelect,
                text = "输出与结果",
                appearance = ButtonAppearance.Subtle
            )
            when (campaign.status) {
                "running" -> LocalizedButton(
                    onClick = { onAction("pause") },
                    text = "暂停下一步",
                    appearance = ButtonAppearance.Subtle,
                    leadingIcon = { Icon(Icons.Outlined.PauseCircle, null, modifier = Modifier.size(15.dp)) }
                )
                "paused" -> LocalizedButton(
                    onClick = { onAction("resume") },
                    text = "继续",
                    appearance = ButtonAppearance.Subtle,
                    leadingIcon = { Icon(Icons.Outlined.PlayArrow, null, modifier = Modifier.size(15.dp)) }
                )
                else -> LocalizedButton(
                    onClick = { onAction("start") },
                    text = if (campaign.status == "queued") "启动" else "重新运行",
                    appearance = ButtonAppearance.Subtle,
                    leadingIcon = { Icon(Icons.Outlined.PlayArrow, null, modifier = Modifier.size(15.dp)) }
                )
            }
            if (campaign.status in setOf("running", "paused", "queued")) {
                LocalizedButton(
                    onClick = { onAction("stop") },
                    text = "停止",
                    appearance = ButtonAppearance.Subtle,
                    intent = ButtonIntent.Destructive,
                    leadingIcon = { Icon(Icons.Outlined.StopCircle, null, modifier = Modifier.size(15.dp)) }
                )
            }
            LocalizedButton(
                onClick = onDelete,
                text = if (deleteConfirm) "确认删除" else "删除",
                appearance = ButtonAppearance.Subtle,
                intent = ButtonIntent.Destructive,
                leadingIcon = { Icon(Icons.Outlined.Delete, null, modifier = Modifier.size(15.dp)) }
            )
        }
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun CampaignDetail(
    controller: AppController,
    deleteConfirm: String,
    onDeleteConfirmChange: (String) -> Unit
) {
    val collection = controller.assetCollection
    val campaign = collection.campaigns.firstOrNull { it.id == collection.selectedCampaignId }
    if (campaign == null) {
        EmptyState("选择一个收集批次", "查看实时输出、审批和已收集资产。")
        return
    }
    var resultFilter by remember(campaign.id) { mutableStateOf("all") }
    var page by remember(campaign.id) { mutableStateOf(1) }
    val pageSize = 20
    val filtered = collection.targets.filter { row ->
        when (resultFilter) {
            "all" -> true
            "http_responded" -> row.verificationStatus in setOf("http_responded", "http_verified")
            "dns_resolved" -> row.verificationStatus == "dns_resolved"
            "unverified" -> row.verificationStatus !in setOf(
                "http_responded", "http_verified", "dns_resolved", "verification_failed"
            )
            else -> row.verificationStatus == resultFilter
        }
    }
    val pages = ((filtered.size + pageSize - 1) / pageSize).coerceAtLeast(1)
    val currentPage = page.coerceIn(1, pages)
    val visible = filtered.drop((currentPage - 1) * pageSize).take(pageSize)

    Column(Modifier.fillMaxSize()) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                LocalizedText(
                    campaign.targets.joinToString("、").ifBlank { "资产收集任务" },
                    fontWeight = FontWeight.SemiBold
                )
                LocalizedText(
                    listOf(
                        statusText(campaign.status),
                        "调用 ${campaign.commands}",
                        "候选 ${campaign.candidates}",
                        "出口 ${campaign.proxyName.ifBlank { campaign.proxyPlanId }}",
                        collection.connectionStatus
                    ).filter(String::isNotBlank).joinToString(" · "),
                    style = SaltTheme.textStyles.sub,
                    color = SaltTheme.colors.subText
                )
            }
            val sid = controller.selectedSession?.id
            LocalizedButton(
                onClick = {
                    controller.openBackendUrl("/api/asset-campaigns/${campaign.id}/export.csv")
                },
                text = "导出 CSV",
                appearance = ButtonAppearance.Subtle,
                leadingIcon = { Icon(Icons.Outlined.Download, null, modifier = Modifier.size(15.dp)) }
            )
            Spacer(Modifier.width(7.dp))
            LocalizedButton(
                onClick = {
                    controller.openNewTaskForAssets(
                        campaign.projectId.ifBlank { collection.selectedProjectId },
                        campaign.id
                    )
                },
                text = "选择资产开始 SRC",
                enabled = campaign.status in setOf("completed", "completed_with_errors", "stopped", "failed") &&
                    campaign.candidates > 0
            )
        }
        Box(Modifier.fillMaxWidth().height(1.dp).background(SaltTheme.colors.stroke))
        if (campaign.approvals.isNotEmpty()) {
            Column(
                modifier = Modifier.fillMaxWidth().padding(12.dp),
                verticalArrangement = Arrangement.spacedBy(7.dp)
            ) {
                LocalizedText("待确认操作", color = SaltTheme.colors.warning, fontWeight = FontWeight.SemiBold)
                campaign.approvals.forEach { approval ->
                    Row(
                        modifier = Modifier.fillMaxWidth()
                            .clip(RoundedCornerShape(8.dp))
                            .background(SaltTheme.colors.warning.copy(alpha = 0.08f))
                            .padding(10.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        Column(Modifier.weight(1f)) {
                            LocalizedText(approval.action.ifBlank { "高危操作" }, fontWeight = FontWeight.Medium)
                            LocalizedText(
                                approval.purpose.ifBlank { approval.detail },
                                style = SaltTheme.textStyles.sub,
                                color = SaltTheme.colors.subText
                            )
                        }
                        LocalizedButton(
                            onClick = { collection.decideApproval(approval.id, true) },
                            text = "允许"
                        )
                        LocalizedButton(
                            onClick = { collection.decideApproval(approval.id, false) },
                            text = "拒绝",
                            appearance = ButtonAppearance.Subtle,
                            intent = ButtonIntent.Destructive
                        )
                    }
                }
            }
        }
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(7.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            LocalizedText("资产存活筛选", style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
            listOf(
                "all" to "全部",
                "http_responded" to "HTTP 响应",
                "dns_resolved" to "DNS 解析",
                "unverified" to "待验证",
                "verification_failed" to "验证失败"
            ).forEach { (value, label) ->
                LocalizedButton(
                    onClick = { resultFilter = value; page = 1 },
                    text = label,
                    appearance = if (resultFilter == value) ButtonAppearance.Filled else ButtonAppearance.Subtle
                )
            }
            Spacer(Modifier.weight(1f))
            LocalizedText(
                "${filtered.size} 个资产",
                style = SaltTheme.textStyles.sub,
                color = SaltTheme.colors.subText
            )
        }
        LazyColumn(
            modifier = Modifier.weight(1f),
            contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 16.dp, vertical = 6.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp)
        ) {
            if (collection.outputs.isNotEmpty()) {
                item {
                    LocalizedText("收集进展", fontWeight = FontWeight.SemiBold)
                }
                items(collection.outputs.takeLast(40), key = { "${it.seq}:${it.message}" }) { line ->
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(6.dp))
                            .background(SaltTheme.colors.background.copy(alpha = 0.5f))
                            .padding(horizontal = 9.dp, vertical = 6.dp),
                        horizontalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        LocalizedText(
                            formatAssetTime(line.createdAt),
                            style = SaltTheme.textStyles.sub,
                            color = SaltTheme.colors.subText,
                            modifier = Modifier.width(130.dp)
                        )
                        LocalizedText(
                            line.message,
                            style = SaltTheme.textStyles.sub,
                            color = if (line.level == "error") SaltTheme.colors.error else SaltTheme.colors.text,
                            modifier = Modifier.weight(1f)
                        )
                    }
                }
                item {
                    LocalizedText("资产结果", fontWeight = FontWeight.SemiBold)
                }
            }
            if (collection.detailLoading) {
                item { LoadingBlock("正在读取结果…") }
            } else if (visible.isEmpty()) {
                item {
                    EmptyState(
                        "暂无匹配资产",
                        "收集仍在运行，或当前筛选条件没有结果。"
                    )
                }
            } else {
                items(visible, key = { it.value }) { asset ->
                    AssetTargetRow(asset)
                }
            }
        }
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            LocalizedText(
                "第 $currentPage / $pages 页",
                style = SaltTheme.textStyles.sub,
                color = SaltTheme.colors.subText,
                modifier = Modifier.weight(1f)
            )
            LocalizedButton(
                onClick = { page = (currentPage - 1).coerceAtLeast(1) },
                text = "上一页",
                appearance = ButtonAppearance.Subtle,
                enabled = currentPage > 1
            )
            LocalizedButton(
                onClick = { page = (currentPage + 1).coerceAtMost(pages) },
                text = "下一页",
                appearance = ButtonAppearance.Subtle,
                enabled = currentPage < pages
            )
        }
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun AssetTargetRow(asset: AssetTargetRow) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(7.dp))
            .background(SaltTheme.colors.background.copy(alpha = 0.5f))
            .padding(horizontal = 10.dp, vertical = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(9.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
            LocalizedText(asset.value, fontWeight = FontWeight.Medium)
            LocalizedText(
                listOf(
                    asset.title,
                    asset.assetType,
                    asset.ip.takeIf(String::isNotBlank)?.let { "IP $it" }.orEmpty(),
                    asset.cname.takeIf(String::isNotBlank)?.let { "CNAME $it" }.orEmpty(),
                    asset.collectionMethod.ifBlank { asset.source }
                ).filter(String::isNotBlank).joinToString(" · "),
                style = SaltTheme.textStyles.sub,
                color = SaltTheme.colors.subText
            )
            asset.observations.forEach { observation ->
                LocalizedText(observation, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
            }
        }
        LocalizedText(
            listOf(
                asset.verificationStatus.ifBlank { "未记录" },
                asset.httpStatus.takeIf(String::isNotBlank)?.let { "HTTP $it" }.orEmpty(),
                asset.httpError
            ).filter(String::isNotBlank).joinToString(" · "),
            style = SaltTheme.textStyles.sub,
            color = when (asset.verificationStatus) {
                "http_responded", "http_verified", "dns_resolved" -> SaltTheme.colors.success
                "verification_failed" -> SaltTheme.colors.error
                else -> SaltTheme.colors.subText
            }
        )
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun CreateCampaignDialog(controller: AppController, onClose: () -> Unit) {
    val collection = controller.assetCollection
    var targets by remember { mutableStateOf("") }
    var excluded by remember { mutableStateOf("") }
    var instruction by remember { mutableStateOf("") }
    var directFallback by remember { mutableStateOf(false) }
    var oneforallPath by remember { mutableStateOf("") }
    var pythonPath by remember { mutableStateOf("") }
    var timeoutSeconds by remember { mutableStateOf("600") }
    var brute by remember { mutableStateOf(false) }

    LocalizedDialogWindow(
        onCloseRequest = onClose,
        title = "新建资产收集任务",
        state = rememberDialogState(
            size = DpSize(720.dp, 680.dp),
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
                verticalArrangement = Arrangement.spacedBy(13.dp)
            ) {
                LocalizedText("新建资产收集任务", style = SaltTheme.textStyles.largeTitle)
                LocalizedText(
                    "项目 ${collection.projects.firstOrNull { it.id == collection.selectedProjectId }?.label.orEmpty()} · " +
                        "模型 ${collection.models.firstOrNull { it.id == collection.selectedModel }?.label.orEmpty()} · " +
                        "出口 ${collection.proxyPlans.firstOrNull { it.id == collection.selectedProxyPlanId }?.label ?: "直连"}",
                    style = SaltTheme.textStyles.sub,
                    color = SaltTheme.colors.subText
                )
                Column(verticalArrangement = Arrangement.spacedBy(7.dp)) {
                    LocalizedText("目标资产或组织主体，每行一个", style = SaltTheme.textStyles.sub)
                    SpiritTextField(targets, { targets = it }, "example.com", singleLine = false)
                }
                Column(verticalArrangement = Arrangement.spacedBy(7.dp)) {
                    LocalizedText("本批次排除项", style = SaltTheme.textStyles.sub)
                    SpiritTextField(excluded, { excluded = it }, "不收集的域名、网段或关键词", singleLine = false)
                }
                Column(verticalArrangement = Arrangement.spacedBy(7.dp)) {
                    LocalizedText("收集要求与特殊情况", style = SaltTheme.textStyles.sub)
                    SpiritTextField(
                        instruction,
                        { instruction = it },
                        "说明需要收集什么、已知线索和限制…",
                        singleLine = false
                    )
                }
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Box(Modifier.weight(1f)) {
                        Column(verticalArrangement = Arrangement.spacedBy(7.dp)) {
                            LocalizedText("OneForAll 路径（可选）", style = SaltTheme.textStyles.sub)
                            SpiritTextField(oneforallPath, { oneforallPath = it }, "D:\\tools\\OneForAll")
                        }
                    }
                    Box(Modifier.weight(1f)) {
                        Column(verticalArrangement = Arrangement.spacedBy(7.dp)) {
                            LocalizedText("Python 解释器（可选）", style = SaltTheme.textStyles.sub)
                            SpiritTextField(pythonPath, { pythonPath = it }, "D:\\tools\\python.exe")
                        }
                    }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Box(Modifier.weight(1f)) {
                        Column(verticalArrangement = Arrangement.spacedBy(7.dp)) {
                            LocalizedText("单次收集超时（秒）", style = SaltTheme.textStyles.sub)
                            SpiritTextField(timeoutSeconds, { timeoutSeconds = it }, "600")
                        }
                    }
                    Row(Modifier.weight(1f), verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            LocalizedText("启用 DNS 枚举", fontWeight = FontWeight.Medium)
                            LocalizedText(
                                "对授权域执行 brute 子域枚举。",
                                style = SaltTheme.textStyles.sub,
                                color = SaltTheme.colors.subText
                            )
                        }
                        Switcher(state = brute, onChange = { brute = it })
                    }
                }
                if (collection.selectedProxyPlanId != "direct") {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            LocalizedText("代理失败时允许直连复核", fontWeight = FontWeight.Medium)
                            LocalizedText(
                                "会暴露本机出口，仅复核失败目标。",
                                style = SaltTheme.textStyles.sub,
                                color = SaltTheme.colors.subText
                            )
                        }
                        Switcher(state = directFallback, onChange = { directFallback = it })
                    }
                }
                collection.error?.let {
                    LocalizedText(it, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.error)
                }
                Spacer(Modifier.weight(1f))
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                    LocalizedButton(
                        onClick = onClose,
                        text = "取消",
                        appearance = ButtonAppearance.Subtle
                    )
                    Spacer(Modifier.width(8.dp))
                    LocalizedButton(
                        onClick = {
                            collection.createCampaign(
                                targets,
                                excluded,
                                instruction,
                                directFallback,
                                oneforallPath,
                                pythonPath,
                                timeoutSeconds,
                                brute
                            )
                            onClose()
                        },
                        text = "创建并启动",
                        enabled = !collection.actionBusy
                    )
                }
            }
        }
    }
}

private fun statusText(status: String): String = when (status) {
    "queued" -> "待启动"
    "running" -> "运行中"
    "paused" -> "已暂停下一步"
    "completed" -> "已完成"
    "completed_with_errors" -> "完成但有错误"
    "failed" -> "失败"
    "stopped" -> "已停止"
    else -> status.ifBlank { "未知" }
}

@Composable
private fun collectionStatusColor(status: String) = when (status) {
    "completed" -> SaltTheme.colors.success
    "completed_with_errors", "paused" -> SaltTheme.colors.warning
    "failed" -> SaltTheme.colors.error
    "running" -> SaltTheme.colors.highlight
    else -> SaltTheme.colors.subText
}

private fun formatAssetTime(value: Double): String = if (value <= 0) {
    "—"
} else {
    runCatching {
        java.time.Instant.ofEpochSecond(value.toLong())
            .atZone(java.time.ZoneId.systemDefault())
            .format(java.time.format.DateTimeFormatter.ofPattern("MM-dd HH:mm:ss"))
    }.getOrDefault(value.toString())
}
