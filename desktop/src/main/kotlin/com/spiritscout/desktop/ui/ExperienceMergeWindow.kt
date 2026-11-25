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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.runtime.Composable
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

@OptIn(UnstableSaltUiApi::class)
@Composable
fun ExperienceMergeWindow(controller: AppController) {
    if (!controller.experienceMergeOpen) return
    LocalizedDialogWindow(
        onCloseRequest = controller::closeExperienceMerge,
        title = "整理相似经验",
        state = rememberDialogState(
            size = DpSize(1040.dp, 780.dp),
            position = WindowPosition.Aligned(Alignment.Center)
        ),
        resizable = true
    ) {
        SaltTheme(configs = SaltConfigs.default(isDarkTheme = controller.darkTheme)) {
            Box(Modifier.fillMaxSize().background(SaltTheme.colors.background)) {
                Column(
                    Modifier.fillMaxSize().padding(24.dp),
                    verticalArrangement = Arrangement.spacedBy(14.dp)
                ) {
                    Column {
                        LocalizedText("整理相似经验", style = SaltTheme.textStyles.largeTitle)
                        LocalizedText(
                            "先查找字符相似候选，再填写 2–6 个经验 ID 生成合并稿。确认前不会修改原件。",
                            style = SaltTheme.textStyles.sub,
                            color = SaltTheme.colors.subText
                        )
                    }
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(10.dp)
                    ) {
                        LocalizedText("字符相似度", style = SaltTheme.textStyles.sub)
                        Box(Modifier.width(120.dp)) {
                            SpiritTextField(
                                controller.experienceMergeThreshold,
                                controller::updateExperienceMergeThreshold,
                                "90"
                            )
                        }
                        LocalizedButton(
                            onClick = controller::loadExperienceMergeCandidates,
                            text = "查找候选",
                            appearance = ButtonAppearance.Subtle
                        )
                        if (controller.experienceMergeLoading) {
                            LocalizedText("处理中…", color = SaltTheme.colors.subText)
                        }
                    }
                    Row(
                        modifier = Modifier.weight(1f).fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(12.dp)
                    ) {
                        CodeCard(
                            title = "候选",
                            value = controller.experienceMergeCandidates,
                            modifier = Modifier.weight(1f).fillMaxHeight()
                        )
                        CodeCard(
                            title = "合并稿 / 预览响应",
                            value = controller.experienceMergeDraft,
                            modifier = Modifier.weight(1f).fillMaxHeight()
                        )
                    }
                    SpiritTextField(
                        controller.experienceMergeIds,
                        controller::updateExperienceMergeIds,
                        "填写候选里的经验 ID，逗号或空格分隔",
                        modifier = Modifier.fillMaxWidth()
                    )
                    controller.experienceMergeError?.let {
                        LocalizedText(it, color = SaltTheme.colors.error, style = SaltTheme.textStyles.sub)
                    }
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.End
                    ) {
                        LocalizedButton(
                            onClick = controller::closeExperienceMerge,
                            text = "关闭",
                            appearance = ButtonAppearance.Subtle
                        )
                        Spacer(Modifier.width(10.dp))
                        LocalizedButton(
                            onClick = controller::previewExperienceMerge,
                            text = "生成合并稿",
                            appearance = ButtonAppearance.Subtle
                        )
                        Spacer(Modifier.width(10.dp))
                        LocalizedButton(
                            onClick = controller::confirmExperienceMerge,
                            text = "确认并保存"
                        )
                    }
                }
            }
        }
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun CodeCard(title: String, value: String, modifier: Modifier = Modifier) {
    Card(modifier, color = SaltTheme.colors.subBackground) {
        Column(Modifier.fillMaxSize().padding(10.dp)) {
            LocalizedText(
                title,
                style = SaltTheme.textStyles.sub,
                color = SaltTheme.colors.subText,
                modifier = Modifier.padding(bottom = 6.dp)
            )
            SpiritCodeEditor(
                value = value,
                onValueChange = {},
                modifier = Modifier.fillMaxSize()
            )
        }
    }
}
