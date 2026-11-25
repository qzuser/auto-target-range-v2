package com.spiritscout.desktop.ui

import androidx.compose.foundation.layout.RowScope
import androidx.compose.material.LocalTextStyle
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextLayoutResult
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.window.DialogWindow
import androidx.compose.ui.window.DialogWindowScope
import androidx.compose.ui.window.DialogState
import com.moriafly.salt.ui.ButtonAppearance
import com.moriafly.salt.ui.ButtonIntent
import com.moriafly.salt.ui.ControlSize
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

object DesktopI18n {
    var language by mutableStateOf("zh-CN")
        private set
    var motionPreference by mutableStateOf("system")
        private set

    private val json = Json { ignoreUnknownKeys = true }
    internal val englishMessages: Map<String, String> by lazy(::loadEnglishMessages)

    fun applyLanguage(value: String) {
        language = if (value == "en-US") "en-US" else "zh-CN"
    }

    fun applyMotionPreference(value: String) {
        motionPreference = value.takeIf {
            it in setOf("system", "soft", "fast", "off")
        } ?: "system"
    }

    fun translate(text: String): String {
        if (language != "en-US" || text.isBlank()) return text
        return englishMessages[text] ?: desktopOverrides[text] ?: text
    }

    private fun loadEnglishMessages(): Map<String, String> {
        val webCatalog = loadResource("/i18n/en.js")
        val desktopCatalog = loadResource("/i18n/desktop-en.json")
        return parseWebCatalog(webCatalog) + parseDesktopCatalog(desktopCatalog)
    }

    private fun loadResource(path: String): String =
        DesktopI18n::class.java
            .getResourceAsStream(path)
            ?.bufferedReader()
            ?.use { it.readText() }
            ?: ""

    private fun parseWebCatalog(content: String): Map<String, String> {
        if (content.isBlank()) return emptyMap()
        val pattern = Regex("\"((?:\\\\.|[^\"\\\\])*)\"\\s*:\\s*\"((?:\\\\.|[^\"\\\\])*)\"")
        return buildMap {
            pattern.findAll(content).forEach { match ->
                val key = decodeJsonString(match.groupValues[1])
                val value = decodeJsonString(match.groupValues[2])
                put(key, value)
            }
        }
    }

    private fun parseDesktopCatalog(content: String): Map<String, String> {
        if (content.isBlank()) return emptyMap()
        return runCatching {
            json.parseToJsonElement(content).jsonObject
                .mapValues { (_, value) -> value.jsonPrimitive.content }
        }.getOrDefault(emptyMap())
    }

    private fun decodeJsonString(raw: String): String =
        runCatching {
            json.parseToJsonElement("\"$raw\"").jsonPrimitive.content
        }.getOrDefault(raw)

    private val desktopOverrides = mapOf(
        "资产收集" to "Asset collection",
        "资产情报" to "Asset intelligence",
        "自动任务" to "Scheduled tasks",
        "编队" to "Agent roster",
        "本地工具" to "Local tools",
        "经验提炼" to "Experience",
        "代理池" to "Proxy pool",
        "浏览器账号" to "Browser accounts",
        "任务工作区" to "Workspace",
        "外观与通知" to "Appearance & notifications",
        "深色主题" to "Dark theme",
        "系统通知" to "System notifications",
        "最近提醒" to "Recent alerts",
        "全部已读" to "Mark all read",
        "存储清理" to "Storage cleanup",
        "清理范围" to "Cleanup scope",
        "精简数据库" to "Compact database",
        "清理下载缓存" to "Clear download caches",
        "清理预览" to "Cleanup preview",
        "确认清理" to "Confirm cleanup",
        "应用更新" to "Application update",
        "更新步骤" to "Update steps",
        "更新日志" to "Changelog",
        "重新检查" to "Check again",
        "更新并重启" to "Update and restart",
        "当前没有可用更新" to "No update available",
        "原生桌面端" to "Native desktop",
        "界面语言" to "Interface language",
        "动效偏好" to "Motion preference",
        "跟随系统" to "Follow system",
        "柔和" to "Soft",
        "快速" to "Fast",
        "关闭" to "Off",
        "中文" to "Chinese",
        "英文" to "English"
    )
}

@Composable
fun LocalizedText(
    text: String,
    modifier: Modifier = Modifier,
    color: Color = Color.Unspecified,
    fontSize: TextUnit = TextUnit.Unspecified,
    fontStyle: FontStyle? = null,
    fontWeight: FontWeight? = null,
    fontFamily: FontFamily? = null,
    letterSpacing: TextUnit = TextUnit.Unspecified,
    textDecoration: TextDecoration? = null,
    textAlign: TextAlign? = null,
    lineHeight: TextUnit = TextUnit.Unspecified,
    overflow: TextOverflow = TextOverflow.Clip,
    softWrap: Boolean = true,
    maxLines: Int = Int.MAX_VALUE,
    minLines: Int = 1,
    onTextLayout: ((TextLayoutResult) -> Unit)? = null,
    style: TextStyle = LocalTextStyle.current
) {
    com.moriafly.salt.ui.Text(
        text = DesktopI18n.translate(text),
        modifier = modifier,
        color = color,
        fontSize = fontSize,
        fontStyle = fontStyle,
        fontWeight = fontWeight,
        fontFamily = fontFamily,
        letterSpacing = letterSpacing,
        textDecoration = textDecoration,
        textAlign = textAlign,
        lineHeight = lineHeight,
        overflow = overflow,
        softWrap = softWrap,
        maxLines = maxLines,
        minLines = minLines,
        onTextLayout = onTextLayout,
        style = style
    )
}

@Composable
fun LocalizedButton(
    onClick: () -> Unit,
    text: String,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    appearance: ButtonAppearance = ButtonAppearance.Filled,
    intent: ButtonIntent = ButtonIntent.Normal,
    size: ControlSize = ControlSize.Regular,
    leadingIcon: (@Composable () -> Unit)? = null
) {
    com.moriafly.salt.ui.Button(
        onClick = onClick,
        text = DesktopI18n.translate(text),
        modifier = modifier,
        enabled = enabled,
        appearance = appearance,
        intent = intent,
        size = size,
        leadingIcon = leadingIcon
    )
}

@Composable
fun LocalizedDialogWindow(
    onCloseRequest: () -> Unit,
    title: String,
    state: DialogState,
    resizable: Boolean = true,
    content: @Composable DialogWindowScope.() -> Unit
) {
    DialogWindow(
        onCloseRequest = onCloseRequest,
        title = DesktopI18n.translate(title),
        state = state,
        resizable = resizable,
        content = content
    )
}
