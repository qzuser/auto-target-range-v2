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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.DpSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.DialogWindow
import androidx.compose.ui.window.WindowPosition
import androidx.compose.ui.window.rememberDialogState
import com.moriafly.salt.ui.Button
import com.moriafly.salt.ui.ButtonAppearance
import com.moriafly.salt.ui.SaltConfigs
import com.moriafly.salt.ui.SaltTheme
import com.moriafly.salt.ui.Text
import com.spiritscout.desktop.AppController

@Composable
fun ApiConsoleWindow(controller: AppController) {
    if (!controller.showApiConsole) return
    LocalizedDialogWindow(
        onCloseRequest = controller::closeApiConsole,
        title = "高级 API 控制台",
        state = rememberDialogState(
            size = DpSize(980.dp, 780.dp),
            position = WindowPosition.Aligned(Alignment.Center)
        ),
        resizable = true
    ) {
        SaltTheme(configs = SaltConfigs.default(isDarkTheme = controller.darkTheme)) {
            Box(Modifier.fillMaxSize().background(SaltTheme.colors.background)) {
                ApiConsoleContent(controller)
            }
        }
    }
}

@Composable
private fun ApiConsoleContent(controller: AppController) {
    var method by remember { mutableStateOf("GET") }
    var path by remember { mutableStateOf("/api/sessions") }
    var body by remember { mutableStateOf("{}") }

    Column(Modifier.fillMaxSize().padding(22.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        LocalizedText("高级 API 控制台", style = SaltTheme.textStyles.largeTitle)
        LocalizedText(
            "专用页面没有覆盖的接口可在这里直接调用。路径相对本机后端。",
            style = SaltTheme.textStyles.sub,
            color = SaltTheme.colors.subText
        )
        Row(horizontalArrangement = Arrangement.spacedBy(7.dp)) {
            listOf("GET", "POST", "PUT", "PATCH", "DELETE").forEach { item ->
                val active = method == item
                Box(
                    Modifier
                        .clip(RoundedCornerShape(50))
                        .background(if (active) SaltTheme.colors.highlight else SaltTheme.colors.subBackground)
                        .clickable { method = item }
                        .padding(horizontal = 12.dp, vertical = 6.dp)
                ) {
                    LocalizedText(
                        item,
                        style = SaltTheme.textStyles.sub,
                        color = if (active) SaltTheme.colors.onHighlight else SaltTheme.colors.subText
                    )
                }
            }
        }
        SpiritTextField(path, { path = it }, "/api/...")
        Row(Modifier.weight(1f), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Column(Modifier.weight(1f)) {
                LocalizedText("请求 JSON", style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
                Spacer(Modifier.height(5.dp))
                SpiritCodeEditor(body, { body = it }, Modifier.fillMaxSize())
            }
            Column(Modifier.weight(1f)) {
                LocalizedText("响应", style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
                Spacer(Modifier.height(5.dp))
                Box(
                    Modifier.fillMaxSize()
                        .clip(RoundedCornerShape(8.dp))
                        .background(SaltTheme.colors.subBackground)
                        .padding(10.dp)
                ) {
                    when {
                        controller.apiConsoleLoading -> LocalizedText("请求中…")
                        controller.apiConsoleError != null -> LocalizedText(
                            controller.apiConsoleError!!,
                            color = SaltTheme.colors.error
                        )
                        else -> SpiritCodeEditor(
                            controller.apiConsoleResponse,
                            {},
                            Modifier.fillMaxSize()
                        )
                    }
                }
            }
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
            LocalizedButton(
                onClick = controller::closeApiConsole,
                text = "关闭",
                appearance = ButtonAppearance.Subtle
            )
            Spacer(Modifier.width(10.dp))
            LocalizedButton(
                onClick = { controller.executeApiConsole(method, path, body) },
                text = "执行请求",
                enabled = !controller.apiConsoleLoading
            )
        }
    }
}
