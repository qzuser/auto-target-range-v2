package com.spiritscout.desktop.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Add
import androidx.compose.material.icons.outlined.DarkMode
import androidx.compose.material.icons.outlined.LightMode
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.moriafly.salt.ui.Button
import com.moriafly.salt.ui.ButtonAppearance
import com.moriafly.salt.ui.Card
import com.moriafly.salt.ui.Icon
import com.moriafly.salt.ui.SaltTheme
import com.moriafly.salt.ui.Text
import com.moriafly.salt.ui.UnstableSaltUiApi
import com.spiritscout.desktop.model.MetricItem
import com.spiritscout.desktop.model.MetricTone
import com.spiritscout.desktop.model.Section

@OptIn(UnstableSaltUiApi::class)
@Composable
fun PageHeader(
    section: Section,
    connected: Boolean,
    onRefresh: () -> Unit,
    onNewTask: () -> Unit,
    darkTheme: Boolean,
    onToggleTheme: () -> Unit,
    trailing: (@Composable () -> Unit)? = null
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Column(modifier = Modifier.weight(1f)) {
            LocalizedText(
                section.title,
                style = SaltTheme.textStyles.largeTitle,
                color = SaltTheme.colors.text
            )
            Spacer(Modifier.height(4.dp))
            LocalizedText(
                section.subtitle,
                style = SaltTheme.textStyles.sub,
                color = SaltTheme.colors.subText
            )
        }
        StatusPill(
            text = if (connected) "本机已连接" else "连接中断",
            color = if (connected) SaltTheme.colors.success else SaltTheme.colors.error
        )
        Spacer(Modifier.width(12.dp))
        trailing?.invoke()
        SpiritIconButton(Icons.Outlined.Refresh, "刷新", onRefresh)
        Spacer(Modifier.width(8.dp))
        SpiritIconButton(
            if (darkTheme) Icons.Outlined.LightMode else Icons.Outlined.DarkMode,
            if (darkTheme) "切换浅色" else "切换深色",
            onToggleTheme
        )
        Spacer(Modifier.width(10.dp))
        LocalizedButton(
            onClick = onNewTask,
            text = "新任务",
            leadingIcon = {
                Icon(Icons.Outlined.Add, contentDescription = null, modifier = Modifier.size(16.dp))
            }
        )
    }
}

@Composable
fun SpiritIconButton(
    icon: ImageVector,
    description: String,
    onClick: () -> Unit,
    enabled: Boolean = true
) {
    Box(
        modifier = Modifier
            .size(36.dp)
            .clip(CircleShape)
            .background(SaltTheme.colors.subBackground)
            .clickable(enabled = enabled, onClick = onClick),
        contentAlignment = Alignment.Center
    ) {
        Icon(
            icon,
            contentDescription = DesktopI18n.translate(description),
            tint = if (enabled) SaltTheme.colors.text else SaltTheme.colors.subText.copy(alpha = 0.45f),
            modifier = Modifier.size(18.dp)
        )
    }
}

@Composable
fun SpiritTextField(
    value: String,
    onValueChange: (String) -> Unit,
    placeholder: String,
    modifier: Modifier = Modifier,
    singleLine: Boolean = true,
    minHeight: Int = 42
) {
    val shape = RoundedCornerShape(10.dp)
    BasicTextField(
        value = value,
        onValueChange = onValueChange,
        modifier = modifier
            .clip(shape)
            .background(SaltTheme.colors.subBackground)
            .border(1.dp, SaltTheme.colors.stroke, shape),
        singleLine = singleLine,
        textStyle = SaltTheme.textStyles.main.copy(color = SaltTheme.colors.text),
        cursorBrush = SolidColor(SaltTheme.colors.highlight),
        decorationBox = { inner ->
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(if (singleLine) minHeight.dp else 110.dp)
                    .padding(horizontal = 14.dp, vertical = 11.dp),
                contentAlignment = if (singleLine) Alignment.CenterStart else Alignment.TopStart
            ) {
                if (value.isBlank()) {
                    LocalizedText(
                        placeholder,
                        style = SaltTheme.textStyles.main,
                        color = SaltTheme.colors.subText
                    )
                }
                inner()
            }
        }
    )
}

@Composable
fun SpiritPasswordField(
    value: String,
    onValueChange: (String) -> Unit,
    placeholder: String,
    modifier: Modifier = Modifier
) {
    val shape = RoundedCornerShape(10.dp)
    BasicTextField(
        value = value,
        onValueChange = onValueChange,
        modifier = modifier
            .clip(shape)
            .background(SaltTheme.colors.subBackground)
            .border(1.dp, SaltTheme.colors.stroke, shape),
        singleLine = true,
        textStyle = SaltTheme.textStyles.main.copy(color = SaltTheme.colors.text),
        cursorBrush = SolidColor(SaltTheme.colors.highlight),
        visualTransformation = PasswordVisualTransformation(),
        decorationBox = { inner ->
            Box(
                modifier = Modifier.fillMaxWidth().height(42.dp)
                    .padding(horizontal = 14.dp, vertical = 11.dp),
                contentAlignment = Alignment.CenterStart
            ) {
                if (value.isBlank()) {
                    LocalizedText(placeholder, style = SaltTheme.textStyles.main, color = SaltTheme.colors.subText)
                }
                inner()
            }
        }
    )
}

@Composable
fun SpiritCodeEditor(
    value: String,
    onValueChange: (String) -> Unit,
    modifier: Modifier = Modifier
) {
    val shape = RoundedCornerShape(8.dp)
    BasicTextField(
        value = value,
        onValueChange = onValueChange,
        modifier = modifier
            .clip(shape)
            .background(SaltTheme.colors.background.copy(alpha = 0.6f))
            .border(1.dp, SaltTheme.colors.stroke, shape),
        textStyle = SaltTheme.textStyles.main.copy(
            color = SaltTheme.colors.text,
            fontFamily = FontFamily.Monospace
        ),
        cursorBrush = SolidColor(SaltTheme.colors.highlight),
        decorationBox = { inner ->
            Box(
                Modifier.fillMaxWidth().padding(12.dp),
                contentAlignment = Alignment.TopStart
            ) {
                inner()
            }
        }
    )
}

@Composable
fun StatusPill(text: String, color: Color) {
    Row(
        modifier = Modifier
            .clip(RoundedCornerShape(50))
            .background(color.copy(alpha = 0.12f))
            .padding(horizontal = 11.dp, vertical = 7.dp),
        horizontalArrangement = Arrangement.spacedBy(7.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Box(Modifier.size(7.dp).clip(CircleShape).background(color))
        LocalizedText(text, style = SaltTheme.textStyles.sub, color = color, fontWeight = FontWeight.Medium)
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
fun MetricCard(metric: MetricItem, modifier: Modifier = Modifier) {
    val tone = when (metric.tone) {
        MetricTone.NORMAL -> SaltTheme.colors.text
        MetricTone.SUCCESS -> SaltTheme.colors.success
        MetricTone.WARNING -> SaltTheme.colors.warning
        MetricTone.ERROR -> SaltTheme.colors.error
    }
    Card(
        modifier = modifier.height(126.dp),
        color = SaltTheme.colors.subBackground
    ) {
        Column(
            modifier = Modifier.fillMaxWidth().padding(18.dp),
            verticalArrangement = Arrangement.SpaceBetween
        ) {
            LocalizedText(metric.label, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
            LocalizedText(
                metric.value,
                fontSize = 28.sp,
                fontWeight = FontWeight.SemiBold,
                color = tone,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
            LocalizedText(
                metric.detail,
                style = SaltTheme.textStyles.sub,
                color = SaltTheme.colors.subText
            )
        }
    }
}

@Composable
fun SectionCaption(text: String, modifier: Modifier = Modifier) {
    LocalizedText(
        text.uppercase(),
        modifier = modifier.padding(horizontal = 4.dp),
        fontSize = 11.sp,
        fontWeight = FontWeight.SemiBold,
        color = SaltTheme.colors.subText
    )
}

@Composable
fun EmptyState(title: String, description: String) {
    Column(
        modifier = Modifier.fillMaxWidth().padding(vertical = 72.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        LocalizedText(title, style = SaltTheme.textStyles.main, fontWeight = FontWeight.SemiBold)
        Spacer(Modifier.height(8.dp))
        LocalizedText(description, style = SaltTheme.textStyles.sub, color = SaltTheme.colors.subText)
    }
}

@Composable
fun LoadingBlock(text: String = "正在加载…") {
    Box(
        modifier = Modifier.fillMaxWidth().padding(vertical = 72.dp),
        contentAlignment = Alignment.Center
    ) {
        LocalizedText(text, style = SaltTheme.textStyles.main, color = SaltTheme.colors.subText)
    }
}

@Composable
fun ErrorBlock(message: String) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(24.dp)
            .clip(RoundedCornerShape(10.dp))
            .background(SaltTheme.colors.error.copy(alpha = 0.08f))
            .padding(20.dp)
    ) {
        LocalizedText("加载失败", fontWeight = FontWeight.SemiBold, color = SaltTheme.colors.error)
        Spacer(Modifier.height(6.dp))
        LocalizedText(message, style = SaltTheme.textStyles.paragraph, color = SaltTheme.colors.text)
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
fun OutlineAction(
    text: String,
    onClick: () -> Unit,
    icon: ImageVector? = null
) {
    LocalizedButton(
        onClick = onClick,
        text = text,
        appearance = ButtonAppearance.Subtle,
        leadingIcon = icon?.let {
            {
                Icon(it, contentDescription = null, modifier = Modifier.size(16.dp))
            }
        }
    )
}
