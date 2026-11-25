package com.spiritscout.desktop.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
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
import com.moriafly.salt.ui.Icon
import com.moriafly.salt.ui.SaltConfigs
import com.moriafly.salt.ui.SaltTheme
import com.moriafly.salt.ui.Text
import com.moriafly.salt.ui.UnstableSaltUiApi
import com.spiritscout.desktop.AppController
import com.spiritscout.desktop.model.boolean
import com.spiritscout.desktop.model.element
import com.spiritscout.desktop.model.objectOrEmpty
import com.spiritscout.desktop.model.string
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive

@OptIn(UnstableSaltUiApi::class)
@Composable
fun UpdateCenterWindow(controller: AppController, onClose: () -> Unit) {
    val state = controller.updateJson?.objectOrEmpty()
    val phase = state?.element("job")?.objectOrEmpty()?.string("phase").orEmpty()
    val active = phase in setOf("preparing", "backup", "switching", "restarting")
    LaunchedEffect(active, phase) {
        if (active) {
            while (isActive) {
                delay(1_500)
                controller.refreshUpdateStatus(details = true)
            }
        }
    }

    LocalizedDialogWindow(
        onCloseRequest = onClose,
        title = "应用更新",
        state = rememberDialogState(
            size = DpSize(760.dp, 680.dp),
            position = WindowPosition.Aligned(Alignment.Center)
        ),
        resizable = true
    ) {
        SaltTheme(configs = SaltConfigs.default(isDarkTheme = controller.darkTheme)) {
            Column(
                Modifier.fillMaxSize().background(SaltTheme.colors.background).padding(24.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        LocalizedText("应用更新", style = SaltTheme.textStyles.largeTitle)
                        LocalizedText(
                            state?.let {
                                "当前 v${it.string("current")} · " +
                                    it.element("installation")?.objectOrEmpty()?.string("label").orEmpty()
                            } ?: "正在读取更新状态…",
                            style = SaltTheme.textStyles.sub,
                            color = SaltTheme.colors.subText
                        )
                    }
                    LocalizedButton(
                        onClick = { controller.checkUpdates() },
                        text = "重新检查",
                        appearance = ButtonAppearance.Subtle,
                        enabled = !active && !controller.updateBusy,
                        leadingIcon = { Icon(Icons.Outlined.Refresh, null, modifier = Modifier.size(15.dp)) }
                    )
                }
                controller.updateError?.let { ErrorBlock(it) }

                val release = state?.element("release")?.objectOrEmpty()
                val job = state?.element("job")?.objectOrEmpty()
                if (state != null) {
                    Row(
                        Modifier.fillMaxWidth()
                            .clip(RoundedCornerShape(8.dp))
                            .background(SaltTheme.colors.subBackground)
                            .padding(14.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Column(Modifier.weight(1f)) {
                            LocalizedText(
                                if (state.boolean("available")) {
                                    "发现新版本 ${release?.string("tag").orEmpty()}"
                                } else {
                                    "当前没有可用更新"
                                },
                                fontWeight = FontWeight.SemiBold
                            )
                            LocalizedText(
                                job?.string("message").orEmpty()
                                    .ifBlank { state.string("reason").ifBlank { state.string("error") } }
                                    .ifBlank { "更新前会备份配置和工作区；完成后服务会重启。" },
                                style = SaltTheme.textStyles.sub,
                                color = if (phase in setOf("error", "recovery_required")) {
                                    SaltTheme.colors.error
                                } else {
                                    SaltTheme.colors.subText
                                }
                            )
                        }
                        if (active) {
                            StatusPill(updatePhaseText(phase), SaltTheme.colors.warning)
                        } else if (phase == "completed") {
                            StatusPill("已完成", SaltTheme.colors.success)
                        } else if (phase == "recovery_required") {
                            StatusPill("需要恢复", SaltTheme.colors.error)
                        }
                    }
                }

                LocalizedText("更新步骤", fontWeight = FontWeight.SemiBold)
                Row(horizontalArrangement = Arrangement.spacedBy(7.dp)) {
                    listOf(
                        "preparing" to "准备",
                        "backup" to "备份",
                        "switching" to "切换",
                        "restarting" to "重启"
                    ).forEachIndexed { index, (key, label) ->
                        val currentIndex = listOf("preparing", "backup", "switching", "restarting").indexOf(phase)
                        StatusPill(
                            label,
                            when {
                                currentIndex > index -> SaltTheme.colors.success
                                currentIndex == index -> SaltTheme.colors.highlight
                                else -> SaltTheme.colors.subText
                            }
                        )
                    }
                }

                LocalizedText("更新日志", fontWeight = FontWeight.SemiBold)
                Column(
                    Modifier.fillMaxWidth()
                        .heightIn(min = 160.dp, max = 300.dp)
                        .clip(RoundedCornerShape(8.dp))
                        .background(SaltTheme.colors.subBackground)
                        .verticalScroll(rememberScrollState())
                        .padding(14.dp),
                    verticalArrangement = Arrangement.spacedBy(6.dp)
                ) {
                    val changelog = release?.string("changelog").orEmpty()
                    LocalizedText(
                        changelog.ifBlank { "发布更新后，这里会展示对应版本的更新日志。" },
                        style = SaltTheme.textStyles.paragraph
                    )
                }
                if (phase == "recovery_required") {
                    LocalizedText(
                        "更新需要人工恢复。请检查本机更新目录中的 job 日志和 backup 目录，避免直接启动旧版本覆盖新版数据。",
                        style = SaltTheme.textStyles.sub,
                        color = SaltTheme.colors.error
                    )
                }
                Spacer(Modifier.weight(1f))
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                    LocalizedButton(onClick = onClose, text = "关闭", appearance = ButtonAppearance.Subtle)
                    Spacer(Modifier.padding(horizontal = 4.dp))
                    LocalizedButton(
                        onClick = {
                            release?.string("tag")?.takeIf(String::isNotBlank)?.let(controller::applyUpdate)
                        },
                        text = if (active) "正在更新…" else "更新并重启",
                        enabled = state?.boolean("can_update") == true && !active && !controller.updateBusy
                    )
                }
            }
        }
    }
}

private fun updatePhaseText(phase: String): String = when (phase) {
    "preparing" -> "正在准备"
    "backup" -> "正在备份"
    "switching" -> "正在切换"
    "restarting" -> "正在重启"
    else -> phase
}
