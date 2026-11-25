package com.spiritscout.desktop.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
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
import androidx.compose.material.icons.outlined.SmartToy
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
import com.moriafly.salt.ui.Icon
import com.moriafly.salt.ui.SaltTheme
import com.moriafly.salt.ui.Text
import com.moriafly.salt.ui.UnstableSaltUiApi
import com.spiritscout.desktop.AppController
import com.spiritscout.desktop.state.AgentRow

@OptIn(UnstableSaltUiApi::class)
@Composable
fun AgentsPage(controller: AppController) {
    val catalog = controller.agentCatalog
    var bulkModel by remember { mutableStateOf("") }
    LaunchedEffect(Unit) { catalog.refresh() }

    Column(Modifier.fillMaxSize().padding(24.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                LocalizedText("编队", style = SaltTheme.textStyles.largeTitle)
                LocalizedText(
                    "为每个专项 Agent 绑定模型；留空表示沿用档位路由。",
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
        }
        Row(
            modifier = Modifier.fillMaxWidth()
                .clip(RoundedCornerShape(8.dp))
                .background(SaltTheme.colors.subBackground)
                .padding(12.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            LocalizedText("统一应用", fontWeight = FontWeight.SemiBold)
            LazyRow(Modifier.weight(1f), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                items(catalog.models) { model ->
                    LocalizedButton(
                        onClick = { bulkModel = model },
                        text = model,
                        appearance = if (bulkModel == model) ButtonAppearance.Filled else ButtonAppearance.Subtle
                    )
                }
            }
            LocalizedButton(
                onClick = { catalog.bindAll(bulkModel) },
                text = "应用到可用角色",
                enabled = bulkModel.isNotBlank() && !catalog.saving
            )
        }
        catalog.error?.let { ErrorBlock(it) }
        if (catalog.message.isNotBlank()) {
            LocalizedText(catalog.message, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.success)
        }
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            items(catalog.agents, key = { it.key }) { agent ->
                AgentCard(controller, agent)
            }
        }
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun AgentCard(controller: AppController, agent: AgentRow) {
    val catalog = controller.agentCatalog
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(SaltTheme.colors.subBackground)
            .padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(9.dp)) {
            Icon(
                Icons.Outlined.SmartToy,
                null,
                modifier = Modifier.size(20.dp),
                tint = SaltTheme.colors.highlight
            )
            Column(Modifier.weight(1f)) {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                    LocalizedText(agent.name, fontWeight = FontWeight.SemiBold)
                    StatusPill(
                        agent.status.ifBlank { "未知" },
                        if (agent.status == "available") SaltTheme.colors.success else SaltTheme.colors.subText
                    )
                }
                LocalizedText(
                    agent.duty,
                    style = SaltTheme.textStyles.sub,
                    color = SaltTheme.colors.subText
                )
            }
            LocalizedText(
                "适用 ${agent.modes.joinToString(" / ").ifBlank { "默认" }}",
                style = SaltTheme.textStyles.sub,
                color = SaltTheme.colors.subText
            )
        }
        LocalizedText(
            "当前模型：${agent.assignedModel.ifBlank { "档位路由（自动）" }}",
            style = SaltTheme.textStyles.sub,
            color = if (agent.assignedModel.isBlank()) SaltTheme.colors.subText else SaltTheme.colors.highlight
        )
        LazyRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            item {
                LocalizedButton(
                    onClick = { catalog.bind(agent.key, "") },
                    text = "自动",
                    appearance = if (agent.assignedModel.isBlank()) ButtonAppearance.Filled else ButtonAppearance.Subtle
                )
            }
            items(catalog.models) { model ->
                LocalizedButton(
                    onClick = { catalog.bind(agent.key, model) },
                    text = model,
                    appearance = if (agent.assignedModel == model) ButtonAppearance.Filled else ButtonAppearance.Subtle
                )
            }
        }
    }
}
