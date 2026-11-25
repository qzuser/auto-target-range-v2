package com.spiritscout.desktop.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
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
import androidx.compose.material.icons.outlined.AttachFile
import androidx.compose.material.icons.outlined.CheckBox
import androidx.compose.material.icons.outlined.CheckBoxOutlineBlank
import androidx.compose.material.icons.outlined.Close
import androidx.compose.material.icons.outlined.ContentPaste
import androidx.compose.material.icons.outlined.FolderOpen
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.DpSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.DialogWindow
import androidx.compose.ui.window.WindowPosition
import androidx.compose.ui.window.rememberDialogState
import com.moriafly.salt.ui.Button
import com.moriafly.salt.ui.ButtonAppearance
import com.moriafly.salt.ui.Card
import com.moriafly.salt.ui.Icon
import com.moriafly.salt.ui.SaltConfigs
import com.moriafly.salt.ui.SaltTheme
import com.moriafly.salt.ui.Switcher
import com.moriafly.salt.ui.Text
import com.moriafly.salt.ui.UnstableSaltUiApi
import com.spiritscout.desktop.AppController
import com.spiritscout.desktop.model.NewTaskRequest
import com.spiritscout.desktop.model.TaskOption
import javax.swing.JFileChooser
import java.awt.dnd.DnDConstants
import java.awt.dnd.DropTarget
import java.awt.dnd.DropTargetAdapter
import java.awt.dnd.DropTargetDragEvent
import java.awt.dnd.DropTargetDropEvent
import java.awt.datatransfer.DataFlavor
import java.io.File

@OptIn(UnstableSaltUiApi::class)
@Composable
fun NewTaskWindow(controller: AppController) {
    if (!controller.showNewTask) return
    LocalizedDialogWindow(
        onCloseRequest = controller::closeNewTask,
        title = "新建灵枢任务",
        state = rememberDialogState(
            size = DpSize(820.dp, 840.dp),
            position = WindowPosition.Aligned(Alignment.Center)
        ),
        resizable = false
    ) {
        DisposableEffect(window) {
            val listener = object : DropTargetAdapter() {
                override fun dragEnter(event: DropTargetDragEvent) {
                    if (event.transferable.isDataFlavorSupported(DataFlavor.javaFileListFlavor)) {
                        event.acceptDrag(DnDConstants.ACTION_COPY)
                    } else {
                        event.rejectDrag()
                    }
                }

                override fun drop(event: DropTargetDropEvent) {
                    if (!event.transferable.isDataFlavorSupported(DataFlavor.javaFileListFlavor)) {
                        event.rejectDrop()
                        return
                    }
                    event.acceptDrop(DnDConstants.ACTION_COPY)
                    try {
                        val dropped = event.transferable
                            .getTransferData(DataFlavor.javaFileListFlavor) as? List<*>
                            ?: emptyList<Any>()
                        val files = dropped.filterIsInstance<File>()
                        controller.addUploads(files.filter(File::isFile).map { it.toPath() })
                        files.filter(File::isDirectory).forEach { controller.addFolderUploads(it.toPath()) }
                        event.dropComplete(true)
                    } catch (_: Exception) {
                        event.dropComplete(false)
                    }
                }
            }
            val target = DropTarget(window, DnDConstants.ACTION_COPY, listener, true)
            onDispose { target.removeDropTargetListener(listener) }
        }
        SaltTheme(configs = SaltConfigs.default(isDarkTheme = controller.darkTheme)) {
            Box(Modifier.fillMaxSize().background(SaltTheme.colors.background)) {
                NewTaskContent(controller)
            }
        }
    }
    if (controller.showRuleConflict) {
        LocalizedDialogWindow(
            onCloseRequest = controller::cancelRuleConflicts,
            title = "确认规则冲突",
            state = rememberDialogState(
                size = DpSize(620.dp, 460.dp),
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
                    verticalArrangement = Arrangement.spacedBy(16.dp)
                ) {
                    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        LocalizedText("任务规则存在冲突", style = SaltTheme.textStyles.largeTitle)
                        LocalizedText(
                            "后端没有创建会话。确认下列冲突仅用于本次任务后，才会带确认标记重新提交。",
                            style = SaltTheme.textStyles.sub,
                            color = SaltTheme.colors.subText
                        )
                    }
                    Card(
                        Modifier
                            .fillMaxWidth()
                            .weight(1f),
                        color = SaltTheme.colors.subBackground
                    ) {
                        Column(
                            Modifier
                                .fillMaxSize()
                                .verticalScroll(rememberScrollState())
                                .padding(16.dp),
                            verticalArrangement = Arrangement.spacedBy(10.dp)
                        ) {
                            controller.taskRuleConflicts.forEachIndexed { index, conflict ->
                                Row(
                                    horizontalArrangement = Arrangement.spacedBy(9.dp),
                                    verticalAlignment = Alignment.Top
                                ) {
                                    LocalizedText(
                                        "${index + 1}.",
                                        color = SaltTheme.colors.error,
                                        fontWeight = FontWeight.SemiBold
                                    )
                                    LocalizedText(conflict, style = SaltTheme.textStyles.sub)
                                }
                            }
                        }
                    }
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.End
                    ) {
                        LocalizedButton(
                            onClick = controller::cancelRuleConflicts,
                            text = "返回修改",
                            appearance = ButtonAppearance.Subtle
                        )
                        Spacer(Modifier.width(10.dp))
                        LocalizedButton(
                            onClick = controller::confirmRuleConflicts,
                            text = "确认并重新提交"
                        )
                    }
                }
            }
        }
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun NewTaskContent(controller: AppController) {
    var title by remember { mutableStateOf("") }
    var mode by remember { mutableStateOf("auto") }
    var target by remember { mutableStateOf("") }
    var mission by remember { mutableStateOf("") }
    var scope by remember { mutableStateOf("") }
    var model by remember { mutableStateOf("自动") }
    var generateWriteup by remember { mutableStateOf(false) }
    var allowSensitive by remember { mutableStateOf(false) }
    var showAdvanced by remember { mutableStateOf(false) }
    var projectId by remember { mutableStateOf("") }
    var proxyPlanId by remember { mutableStateOf("direct") }
    var assetStrategy by remember { mutableStateOf("edge_first") }
    var excludedAssets by remember { mutableStateOf("") }
    var platform by remember { mutableStateOf("") }
    var flagFormat by remember { mutableStateOf("") }
    var ctfHints by remember { mutableStateOf(setOf<String>()) }
    var ctfNote by remember { mutableStateOf("") }
    var challengeName by remember { mutableStateOf("") }
    var challengeAddress by remember { mutableStateOf("") }
    var challengeDescription by remember { mutableStateOf("") }
    var challengeHint by remember { mutableStateOf("") }
    var challengesYaml by remember { mutableStateOf("") }
    var platformYaml by remember { mutableStateOf("") }
    var contestType by remember { mutableStateOf("") }
    var budgetTokens by remember { mutableStateOf("") }
    var rps by remember { mutableStateOf("10") }
    var rulesYaml by remember { mutableStateOf("") }
    var multipleAnswers by remember { mutableStateOf(false) }
    var noLlm by remember { mutableStateOf(false) }
    var acceptRuleConflicts by remember { mutableStateOf(false) }
    var selectedAssetValues by remember { mutableStateOf(setOf<String>()) }
    var selectedCampaignId by remember { mutableStateOf("") }
    var selectedBrowserAccountIds by remember { mutableStateOf(setOf<String>()) }
    var validation by remember { mutableStateOf<String?>(null) }
    var initializedFromAssetHandoff by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) {
        if (!initializedFromAssetHandoff &&
            controller.taskInitialProjectId.isNotBlank() &&
            controller.taskInitialCampaignId.isNotBlank()
        ) {
            mode = "src"
            projectId = controller.taskInitialProjectId
            selectedCampaignId = controller.taskInitialCampaignId
            controller.loadTaskAssetCampaigns(projectId)
            controller.loadTaskAssetTargets(selectedCampaignId)
            initializedFromAssetHandoff = true
        }
    }

    LaunchedEffect(
        controller.taskAssetTargetsCampaignId,
        controller.taskAssetTargets.map { it.id }
    ) {
        if (controller.taskAssetTargetsCampaignId == selectedCampaignId) {
            selectedAssetValues = controller.taskAssetTargets
                .filter { it.selectedByDefault }
                .map { it.id }
                .toSet()
        }
    }

    Column(
        modifier = Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(26.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        Column {
            LocalizedText("下达新任务", style = SaltTheme.textStyles.largeTitle)
            LocalizedText(
                "选择执行模式并写清目标、授权范围与期望结果。",
                style = SaltTheme.textStyles.sub,
                color = SaltTheme.colors.subText
            )
        }

        Field("任务名称") {
            SpiritTextField(title, { title = it }, "不填则按目标或任务内容自动命名")
        }

        Field("执行模式") {
            LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                items(
                    listOf(
                        "auto" to "自动判断",
                        "src" to "SRC 渗透",
                        "ctf" to "CTF 解题",
                        "competition" to "智能渗透赛",
                        "awdp" to "AWDP 修补"
                    )
                ) { option ->
                    ChoiceChip(option.second, mode == option.first) {
                        mode = option.first
                        if (mode != "src") {
                            selectedCampaignId = ""
                            selectedAssetValues = emptySet()
                            controller.loadTaskAssetCampaigns("")
                        } else if (projectId.isNotBlank()) {
                            controller.loadTaskAssetCampaigns(projectId)
                        }
                    }
                }
            }
        }

        if (mode == "ctf") {
            Card(Modifier.fillMaxWidth(), color = SaltTheme.colors.subBackground) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    LocalizedText("CTF 题目信息", fontWeight = FontWeight.SemiBold)
                    Row(horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                        Field("题目名称", Modifier.weight(1f)) {
                            SpiritTextField(challengeName, { challengeName = it }, "例如：登录迷局")
                        }
                        Field("题目地址", Modifier.weight(1f)) {
                            SpiritTextField(
                                challengeAddress,
                                { challengeAddress = it },
                                "URL、主机端口或连接指令"
                            )
                        }
                    }
                    Field("题目描述") {
                        SpiritTextField(
                            challengeDescription,
                            { challengeDescription = it },
                            "粘贴题目原文、背景和解題要求",
                            singleLine = false
                        )
                    }
                    Field("题目提示") {
                        SpiritTextField(
                            challengeHint,
                            { challengeHint = it },
                            "赛方提示或补充线索",
                            singleLine = false
                        )
                    }
                    Field("题型提示") {
                        LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            items(
                                listOf(
                                    "Web", "Pwn", "Reverse", "Crypto", "Misc",
                                    "IoT", "AI 安全", "移动安全", "区块链", "取证"
                                )
                            ) { type ->
                                ChoiceChip(type, type in ctfHints) {
                                    ctfHints = if (type in ctfHints) ctfHints - type else ctfHints + type
                                }
                            }
                        }
                    }
                    Field("补充题型") {
                        SpiritTextField(ctfNote, { ctfNote = it }, "其他题型或方向，可留空")
                    }
                }
            }
        }

        Row(horizontalArrangement = Arrangement.spacedBy(14.dp)) {
            Field("目标", Modifier.weight(1f)) {
                SpiritTextField(target, { target = it }, "域名、URL、IP 或题目标识")
            }
            Field("授权范围", Modifier.weight(1f)) {
                SpiritTextField(scope, { scope = it }, "每行一个目标；留空时使用目标")
            }
        }

        Field("任务说明") {
            SpiritTextField(
                mission,
                { mission = it },
                "说明业务目标、已知线索、限制条件和期望交付物…",
                singleLine = false
            )
        }

        Field("附件") {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    LocalizedButton(
                        onClick = {
                            val chooser = JFileChooser().apply {
                                isMultiSelectionEnabled = true
                                dialogTitle = "选择要随任务提交的文件"
                            }
                            if (chooser.showOpenDialog(null) == JFileChooser.APPROVE_OPTION) {
                                controller.addUploads(chooser.selectedFiles.map { it.toPath() })
                            }
                        },
                        text = if (controller.uploading) "正在上传…" else "添加附件",
                        appearance = ButtonAppearance.Subtle,
                        leadingIcon = {
                            Icon(Icons.Outlined.AttachFile, null, modifier = Modifier.padding(1.dp))
                        }
                    )
                    LocalizedButton(
                        onClick = {
                            val chooser = JFileChooser().apply {
                                fileSelectionMode = JFileChooser.DIRECTORIES_ONLY
                                isMultiSelectionEnabled = false
                                dialogTitle = "选择要上传的文件夹"
                            }
                            if (chooser.showOpenDialog(null) == JFileChooser.APPROVE_OPTION) {
                                chooser.selectedFile?.toPath()?.let(controller::addFolderUploads)
                            }
                        },
                        text = "添加文件夹",
                        appearance = ButtonAppearance.Subtle,
                        leadingIcon = {
                            Icon(Icons.Outlined.FolderOpen, null, modifier = Modifier.padding(1.dp))
                        }
                    )
                    LocalizedButton(
                        onClick = controller::addClipboardImage,
                        text = "粘贴图片",
                        appearance = ButtonAppearance.Subtle,
                        leadingIcon = {
                            Icon(Icons.Outlined.ContentPaste, null, modifier = Modifier.padding(1.dp))
                        }
                    )
                    if (controller.pendingUploads.isNotEmpty()) {
                        LocalizedText(
                            "已选择 ${controller.pendingUploads.size} 个文件",
                            style = SaltTheme.textStyles.sub,
                            color = SaltTheme.colors.subText,
                            modifier = Modifier.padding(top = 9.dp)
                        )
                    }
                }
                LocalizedText(
                    "可直接拖入文件或文件夹；单文件、单文件夹上限 50 MB，文件夹会保留目录结构。",
                    style = SaltTheme.textStyles.sub,
                    color = SaltTheme.colors.subText
                )
                if (controller.pendingUploads.isNotEmpty()) {
                    LazyRow(horizontalArrangement = Arrangement.spacedBy(7.dp)) {
                        items(controller.pendingUploads, key = { it.id }) { upload ->
                            Row(
                                modifier = Modifier
                                    .clip(RoundedCornerShape(50))
                                    .background(SaltTheme.colors.subBackground)
                                    .padding(start = 11.dp, end = 5.dp, top = 5.dp, bottom = 5.dp),
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.spacedBy(5.dp)
                            ) {
                                LocalizedText(upload.name, style = SaltTheme.textStyles.sub)
                                Box(
                                    Modifier.size(20.dp).clip(RoundedCornerShape(50))
                                        .clickable { controller.removeUpload(upload.id) },
                                    contentAlignment = Alignment.Center
                                ) {
                                    Icon(
                                        Icons.Outlined.Close,
                                        "移除附件",
                                        modifier = Modifier.size(13.dp),
                                        tint = SaltTheme.colors.subText
                                    )
                                }
                            }
                        }
                    }
                }
                if (controller.failedUploads.isNotEmpty()) {
                    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        LocalizedText(
                            "上传失败",
                            style = SaltTheme.textStyles.sub,
                            color = SaltTheme.colors.error,
                            fontWeight = FontWeight.Medium
                        )
                        controller.failedUploads.forEach { upload ->
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clip(RoundedCornerShape(8.dp))
                                    .background(SaltTheme.colors.background)
                                    .padding(horizontal = 10.dp, vertical = 7.dp),
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.spacedBy(8.dp)
                            ) {
                                Column(Modifier.weight(1f)) {
                                    LocalizedText(upload.name, style = SaltTheme.textStyles.sub)
                                    LocalizedText(
                                        upload.error ?: "上传失败",
                                        style = SaltTheme.textStyles.sub,
                                        color = SaltTheme.colors.error
                                    )
                                }
                                LocalizedButton(
                                    onClick = { controller.retryUpload(upload.id) },
                                    text = "重试",
                                    appearance = ButtonAppearance.Subtle,
                                    leadingIcon = {
                                        Icon(
                                            Icons.Outlined.Refresh,
                                            null,
                                            modifier = Modifier.size(14.dp)
                                        )
                                    }
                                )
                            }
                        }
                    }
                }
            }
        }

        Field("模型") {
            LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                items(controller.models.ifEmpty { listOf("自动") }) { item ->
                    ChoiceChip(item, model == item) { model = item }
                }
            }
        }

        Card(Modifier.fillMaxWidth(), color = SaltTheme.colors.subBackground) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
                if (controller.taskOptionsLoading) {
                    Row(
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Icon(Icons.Outlined.Refresh, null, modifier = Modifier.size(15.dp))
                        LocalizedText("正在读取项目、代理和浏览器账号…", style = SaltTheme.textStyles.sub)
                    }
                }
                Field("项目") {
                    LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        item {
                            ChoiceChip("未分类", projectId.isBlank()) {
                                projectId = ""
                                selectedCampaignId = ""
                                selectedAssetValues = emptySet()
                                controller.loadTaskAssetCampaigns("")
                            }
                        }
                        items(controller.taskProjects, key = { "project:${it.id}" }) { project ->
                            ChoiceChip(project.label, projectId == project.id) {
                                projectId = project.id
                                selectedCampaignId = ""
                                selectedAssetValues = emptySet()
                                controller.loadTaskAssetCampaigns(
                                    project.id.takeIf { mode == "src" }.orEmpty()
                                )
                            }
                        }
                    }
                }
                if (mode == "src") {
                    Field("代理出口") {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            LazyRow(
                                modifier = Modifier.weight(1f),
                                horizontalArrangement = Arrangement.spacedBy(8.dp)
                            ) {
                                item {
                                    ChoiceChip("直连", proxyPlanId == "direct") {
                                        proxyPlanId = "direct"
                                    }
                                }
                                items(controller.taskProxyPlans, key = { "proxy:${it.id}" }) { plan ->
                                    ChoiceChip(plan.label, proxyPlanId == plan.id) {
                                        proxyPlanId = plan.id
                                    }
                                }
                            }
                            LocalizedButton(
                                onClick = {
                                    controller.closeNewTask()
                                    controller.navigate(com.spiritscout.desktop.model.Section.PROXIES)
                                },
                                text = "管理代理池",
                                appearance = ButtonAppearance.Subtle
                            )
                        }
                    }
                }
                if (controller.taskBrowserAccounts.isNotEmpty()) {
                    Field("浏览器账号") {
                        LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            items(controller.taskBrowserAccounts, key = { "account:${it.id}" }) { account ->
                                val selected = account.id in selectedBrowserAccountIds
                                val label = if (account.detail.isBlank()) account.label else "${account.label} · ${account.detail}"
                                ChoiceChip(label, selected) {
                                    selectedBrowserAccountIds = when {
                                        selected -> selectedBrowserAccountIds - account.id
                                        selectedBrowserAccountIds.size >= 6 -> selectedBrowserAccountIds
                                        else -> selectedBrowserAccountIds + account.id
                                    }
                                }
                            }
                        }
                        LocalizedText(
                            "最多绑定 6 个账号；凭据不会在桌面端回显。",
                            style = SaltTheme.textStyles.sub,
                            color = SaltTheme.colors.subText
                        )
                    }
                }
                if (mode == "src" && projectId.isNotBlank()) {
                    Field("已收集资产") {
                        when {
                            controller.taskCampaignsLoading -> LocalizedText(
                                "正在读取已结束的收集批次…",
                                style = SaltTheme.textStyles.sub,
                                color = SaltTheme.colors.subText
                            )
                            controller.taskAssetCampaigns.isEmpty() -> LocalizedText(
                                "该项目暂无可交接的已完成资产批次。",
                                style = SaltTheme.textStyles.sub,
                                color = SaltTheme.colors.subText
                            )
                            else -> {
                                LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                    items(controller.taskAssetCampaigns, key = { "campaign:${it.id}" }) { campaign ->
                                        val label = if (campaign.detail.isBlank()) {
                                            campaign.label
                                        } else {
                                            "${campaign.label} · ${campaign.detail}"
                                        }
                                        ChoiceChip(label, selectedCampaignId == campaign.id) {
                                            selectedCampaignId = campaign.id
                                            selectedAssetValues = emptySet()
                                            controller.loadTaskAssetTargets(campaign.id)
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
                if (selectedCampaignId.isNotBlank()) {
                    Field("本次测试资产") {
                        Column(verticalArrangement = Arrangement.spacedBy(9.dp)) {
                            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                LocalizedButton(
                                    onClick = {
                                        selectedAssetValues = controller.taskAssetTargets.map { it.id }.toSet()
                                    },
                                    text = "全选",
                                    appearance = ButtonAppearance.Subtle
                                )
                                LocalizedButton(
                                    onClick = { selectedAssetValues = emptySet() },
                                    text = "清空",
                                    appearance = ButtonAppearance.Subtle
                                )
                                LocalizedText(
                                    "已选 ${selectedAssetValues.size} 个资产",
                                    style = SaltTheme.textStyles.sub,
                                    color = SaltTheme.colors.subText,
                                    modifier = Modifier.padding(top = 9.dp)
                                )
                            }
                            if (controller.taskTargetsLoading) {
                                LocalizedText(
                                    "正在读取资产清单…",
                                    style = SaltTheme.textStyles.sub,
                                    color = SaltTheme.colors.subText
                                )
                            } else if (controller.taskAssetTargets.isEmpty()) {
                                LocalizedText(
                                    "该批次暂无可选资产。",
                                    style = SaltTheme.textStyles.sub,
                                    color = SaltTheme.colors.subText
                                )
                            } else {
                                LazyColumn(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .heightIn(max = 280.dp),
                                    verticalArrangement = Arrangement.spacedBy(6.dp)
                                ) {
                                    items(controller.taskAssetTargets, key = { "asset:${it.id}" }) { asset ->
                                        val checked = asset.id in selectedAssetValues
                                        Row(
                                            modifier = Modifier
                                                .fillMaxWidth()
                                                .clip(RoundedCornerShape(8.dp))
                                                .background(
                                                    if (checked) SaltTheme.colors.highlight
                                                    else SaltTheme.colors.background
                                                )
                                                .clickable {
                                                    selectedAssetValues = if (checked) {
                                                        selectedAssetValues - asset.id
                                                    } else {
                                                        selectedAssetValues + asset.id
                                                    }
                                                }
                                                .padding(horizontal = 11.dp, vertical = 9.dp),
                                            verticalAlignment = Alignment.CenterVertically,
                                            horizontalArrangement = Arrangement.spacedBy(9.dp)
                                        ) {
                                            Icon(
                                                if (checked) Icons.Outlined.CheckBox
                                                else Icons.Outlined.CheckBoxOutlineBlank,
                                                null,
                                                modifier = Modifier.size(17.dp),
                                                tint = if (checked) SaltTheme.colors.highlight
                                                else SaltTheme.colors.subText
                                            )
                                            Column(Modifier.weight(1f)) {
                                                LocalizedText(
                                                    asset.label,
                                                    style = SaltTheme.textStyles.sub,
                                                    color = if (checked) SaltTheme.colors.onHighlight
                                                    else SaltTheme.colors.text
                                                )
                                                if (asset.detail.isNotBlank()) {
                                                    LocalizedText(
                                                        asset.detail,
                                                        style = SaltTheme.textStyles.sub,
                                                        color = if (checked) SaltTheme.colors.onHighlight
                                                        else SaltTheme.colors.subText
                                                    )
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        LocalizedButton(
            onClick = { showAdvanced = !showAdvanced },
            text = if (showAdvanced) "收起高级选项" else "展开高级选项",
            appearance = ButtonAppearance.Subtle
        )

        if (showAdvanced) {
            Field("资产策略") {
                LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    items(
                        listOf(
                            "edge_first" to "边缘优先",
                            "core_first" to "核心优先",
                            "balanced" to "均衡"
                        )
                    ) { option ->
                        ChoiceChip(option.second, assetStrategy == option.first) {
                            assetStrategy = option.first
                        }
                    }
                }
            }
            Field("排除资产") {
                SpiritTextField(
                    excludedAssets,
                    { excludedAssets = it },
                    "每行一个；不测试的域名、网段或资产",
                    singleLine = false
                )
            }
            Row(horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                Field("平台", Modifier.weight(1f)) {
                    SpiritTextField(platform, { platform = it }, "CTF 平台或比赛名称")
                }
                Field("Flag 格式", Modifier.weight(1f)) {
                    SpiritTextField(flagFormat, { flagFormat = it }, "例如 flag{...}")
                }
            }
            Field("赛制") {
                SpiritTextField(contestType, { contestType = it }, "例如 jeopardy / awdp")
            }
            Row(horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                Field("预算 Token", Modifier.weight(1f)) {
                    SpiritTextField(budgetTokens, { budgetTokens = it }, "留空不设上限")
                }
                Field("RPS", Modifier.weight(1f)) {
                    SpiritTextField(rps, { rps = it }, "默认 10")
                }
            }
            Field("赛题 YAML") {
                SpiritTextField(
                    challengesYaml,
                    { challengesYaml = it },
                    "可选：批量赛题的 challenges_yaml；留空时由桌面表单或 Agent 推断",
                    singleLine = false
                )
            }
            Field("平台 YAML") {
                SpiritTextField(
                    platformYaml,
                    { platformYaml = it },
                    "可选：托管题平台的 platform_yaml",
                    singleLine = false
                )
            }
            Field("规则 YAML") {
                SpiritTextField(
                    rulesYaml,
                    { rulesYaml = it },
                    "可选：粘贴比赛规则或额外限制",
                    singleLine = false
                )
            }
            Card(Modifier.fillMaxWidth(), color = SaltTheme.colors.subBackground) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
                    SwitchLine(
                        title = "允许多个答案",
                        description = "适用于多 Flag、多答案赛题",
                        checked = multipleAnswers
                    ) { multipleAnswers = it }
                    SwitchLine(
                        title = "无模型本地模式",
                        description = "只运行本地工具与审计流程",
                        checked = noLlm
                    ) { noLlm = it }
                    SwitchLine(
                        title = "接受规则冲突",
                        description = "任务发起时直接确认规则冲突",
                        checked = acceptRuleConflicts
                    ) { acceptRuleConflicts = it }
                }
            }
        }

        Card(Modifier.fillMaxWidth(), color = SaltTheme.colors.subBackground) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
                SwitchLine(
                    title = "生成解题/测试报告",
                    description = "任务完成后生成可下载报告",
                    checked = generateWriteup
                ) { generateWriteup = it }
                SwitchLine(
                    title = "允许敏感操作",
                    description = "仍需遵守会话授权边界和审批策略",
                    checked = allowSensitive
                ) { allowSensitive = it }
            }
        }

        val error = validation ?: controller.taskError
        if (error != null) {
            LocalizedText(error, color = SaltTheme.colors.error, style = SaltTheme.textStyles.sub)
        }

        Spacer(Modifier.height(8.dp))
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.End,
            verticalAlignment = Alignment.CenterVertically
        ) {
            LocalizedButton(
                onClick = controller::closeNewTask,
                text = "取消",
                appearance = ButtonAppearance.Subtle
            )
            Spacer(Modifier.width(10.dp))
            LocalizedButton(
                onClick = {
                    val effectiveTarget = target.trim().ifBlank {
                        if (mode == "ctf") challengeAddress.trim() else ""
                    }
                    val challengeText = listOf(
                        "题目名称" to challengeName.trim(),
                        "题目描述" to challengeDescription.trim(),
                        "题目提示" to challengeHint.trim(),
                        "题目地址" to challengeAddress.trim()
                    ).filter { it.second.isNotBlank() }
                        .joinToString("\n\n") { "${it.first}：\n${it.second}" }
                    val effectiveMission = listOf(challengeText, mission.trim())
                        .filter(String::isNotBlank)
                        .joinToString("\n\n")
                    if (effectiveTarget.isBlank() && effectiveMission.isBlank()) {
                        validation = "至少填写目标、任务说明或 CTF 题目资料。"
                        return@LocalizedButton
                    }
                    if (selectedCampaignId.isNotBlank() && selectedAssetValues.isEmpty()) {
                        validation = "已选择资产批次，请至少勾选一个本次测试资产。"
                        return@LocalizedButton
                    }
                    validation = null
                    val scopeValues = scope.lines().map { it.trim() }.filter { it.isNotBlank() }
                    val excludedValues = (
                        excludedAssets.lines().map { it.trim() }.filter { it.isNotBlank() } +
                            controller.taskAssetExcludedAssets
                        ).distinct()
                    controller.createTask(
                        NewTaskRequest(
                            title = title.trim().ifBlank { challengeName.trim() },
                            mode = mode,
                            target = effectiveTarget,
                            mission = effectiveMission,
                            scope = scopeValues,
                            model = if (model == "自动") "" else model,
                            generateWriteup = generateWriteup,
                            allowSensitive = allowSensitive,
                            projectId = projectId.trim(),
                            proxyPlanId = proxyPlanId.trim().ifBlank { "direct" },
                            assetStrategy = assetStrategy,
                            assetCampaignId = selectedCampaignId,
                            assetValues = selectedAssetValues.toList(),
                            excludedAssets = excludedValues,
                            platform = platform.trim(),
                            flagFormat = flagFormat.trim(),
                            multipleAnswers = mode == "ctf" && multipleAnswers,
                            ctfTypeHints = ctfHints.toList(),
                            ctfTypeNote = ctfNote.trim(),
                            challengesYaml = challengesYaml.trim(),
                            platformYaml = platformYaml.trim(),
                            rulesYaml = rulesYaml.trim(),
                            contestType = contestType.trim(),
                            budgetTokens = budgetTokens.trim().toLongOrNull(),
                            rps = rps.trim().toDoubleOrNull()?.coerceAtLeast(0.1) ?: 10.0,
                            noLlm = noLlm,
                            acceptRuleConflicts = acceptRuleConflicts,
                            browserAccountIds = selectedBrowserAccountIds.toList()
                        )
                    ) { session -> controller.openSession(session) }
                },
                text = "创建并开始",
                leadingIcon = {
                    Icon(Icons.Outlined.Add, null, modifier = Modifier.padding(1.dp))
                }
            )
        }
    }
}

@Composable
private fun Field(
    label: String,
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit
) {
    Column(modifier, verticalArrangement = Arrangement.spacedBy(7.dp)) {
        LocalizedText(label, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText, fontWeight = FontWeight.Medium)
        content()
    }
}

@Composable
private fun ChoiceChip(text: String, selected: Boolean, onClick: () -> Unit) {
    val bg = if (selected) SaltTheme.colors.highlight else SaltTheme.colors.subBackground
    val fg = if (selected) SaltTheme.colors.onHighlight else SaltTheme.colors.text
    Box(
        modifier = Modifier
            .clip(RoundedCornerShape(50))
            .background(bg)
            .clickable(onClick = onClick)
            .padding(horizontal = 13.dp, vertical = 8.dp)
    ) {
        LocalizedText(text, style = SaltTheme.textStyles.sub, color = fg, fontWeight = FontWeight.Medium)
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
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(14.dp)
    ) {
        Column(Modifier.weight(1f)) {
            LocalizedText(title, fontWeight = FontWeight.Medium)
            LocalizedText(description, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
        }
        Switcher(state = checked, onChange = onChange)
    }
}
