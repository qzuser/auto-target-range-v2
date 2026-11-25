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
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.DpSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.DialogWindow
import androidx.compose.ui.window.WindowPosition
import androidx.compose.ui.window.rememberDialogState
import com.moriafly.salt.ui.Button
import com.moriafly.salt.ui.ButtonAppearance
import com.moriafly.salt.ui.Card
import com.moriafly.salt.ui.SaltConfigs
import com.moriafly.salt.ui.SaltTheme
import com.moriafly.salt.ui.Text
import com.moriafly.salt.ui.UnstableSaltUiApi
import com.spiritscout.desktop.AppController

@Composable
fun JsonActionWindow(controller: AppController) {
    val action = controller.jsonAction ?: return
    LocalizedDialogWindow(
        onCloseRequest = controller::closeJsonAction,
        title = action.title,
        state = rememberDialogState(
            size = DpSize(820.dp, 720.dp),
            position = WindowPosition.Aligned(Alignment.Center)
        ),
        resizable = true
    ) {
        SaltTheme(configs = SaltConfigs.default(isDarkTheme = controller.darkTheme)) {
            Box(Modifier.fillMaxSize().background(SaltTheme.colors.background)) {
                JsonActionContent(controller)
            }
        }
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun JsonActionContent(controller: AppController) {
    val action = controller.jsonAction ?: return
    var identifier by remember(action) { mutableStateOf(action.initialId) }
    var text by remember(action) { mutableStateOf(action.initialJson) }

    Column(Modifier.fillMaxSize().padding(24.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        Column {
            LocalizedText(action.title, style = SaltTheme.textStyles.largeTitle)
            LocalizedText(action.description, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
        }
        if (action.requiresId) {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                LocalizedText(action.idLabel, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
                SpiritTextField(identifier, { identifier = it }, action.idLabel)
            }
        }
        if (action.method.uppercase() != "DELETE") {
            Card(Modifier.weight(1f).fillMaxWidth(), color = SaltTheme.colors.subBackground) {
                Column(Modifier.fillMaxSize().padding(10.dp)) {
                    LocalizedText(
                        "JSON",
                        style = SaltTheme.textStyles.sub,
                        color = SaltTheme.colors.subText,
                        modifier = Modifier.padding(bottom = 6.dp)
                    )
                    SpiritCodeEditor(
                        value = text,
                        onValueChange = { text = it },
                        modifier = Modifier.fillMaxSize()
                    )
                }
            }
        } else {
            LocalizedText("此操作会删除当前条目，确认后不可撤销。", color = SaltTheme.colors.error)
        }
        controller.jsonActionError?.let {
            LocalizedText(it, color = SaltTheme.colors.error, style = SaltTheme.textStyles.sub)
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
            LocalizedButton(
                onClick = controller::closeJsonAction,
                text = "取消",
                appearance = ButtonAppearance.Subtle
            )
            Spacer(Modifier.width(10.dp))
            LocalizedButton(
                onClick = { controller.submitJsonAction(identifier, text) },
                text = if (action.method.equals("DELETE", ignoreCase = true)) "确认删除" else "保存"
            )
        }
    }
}
