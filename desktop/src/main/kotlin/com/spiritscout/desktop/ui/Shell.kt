package com.spiritscout.desktop.ui

import androidx.compose.animation.Crossfade
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.Image
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
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.CheckCircle
import androidx.compose.material.icons.outlined.CloudOff
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.moriafly.salt.ui.Card
import com.moriafly.salt.ui.Icon
import com.moriafly.salt.ui.SaltTheme
import com.moriafly.salt.ui.Text
import com.moriafly.salt.ui.UnstableSaltUiApi
import com.spiritscout.desktop.AppController
import com.spiritscout.desktop.model.NavGroup
import com.spiritscout.desktop.model.Section
import kotlinx.coroutines.delay

@Composable
fun SpiritScoutRoot(controller: AppController, captionBarHeight: Dp) {
    Box(Modifier.fillMaxSize()) {
        when {
            controller.booting -> BootPage(controller.bootMessage)
            controller.bootError != null -> FatalPage(controller.bootError!!)
            controller.requiresLogin -> LoginPage(controller)
            else -> {
                Row(Modifier.fillMaxSize().padding(top = captionBarHeight)) {
                    Sidebar(controller)
                    MainSurface(controller)
                }
            }
        }

        controller.toast?.let { message ->
            LaunchedEffect(message) {
                delay(2800)
                controller.clearToast()
            }
            Box(
                modifier = Modifier
                    .align(Alignment.BottomCenter)
                    .padding(bottom = 26.dp)
                    .clip(RoundedCornerShape(50))
                    .background(SaltTheme.colors.popup)
                    .padding(horizontal = 18.dp, vertical = 10.dp)
            ) {
                LocalizedText(message, style = SaltTheme.textStyles.main)
            }
        }
    }
    NewTaskWindow(controller)
    JsonActionWindow(controller)
    ExperienceMergeWindow(controller)
    ApiConsoleWindow(controller)
}

@Composable
private fun MainSurface(controller: AppController) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(SaltTheme.colors.background)
    ) {
        if (controller.section != Section.WORKSPACE) {
            Box(Modifier.fillMaxWidth().padding(horizontal = 28.dp, vertical = 18.dp)) {
                PageHeader(
                    section = controller.section,
                    connected = controller.backendUrl.isNotBlank(),
                    onRefresh = controller::refreshCurrent,
                    onNewTask = controller::openNewTask,
                    darkTheme = controller.darkTheme,
                    onToggleTheme = controller::toggleTheme
                )
            }
            Box(Modifier.fillMaxWidth().height(1.dp).background(SaltTheme.colors.stroke))
        }
        Box(Modifier.weight(1f).fillMaxWidth()) {
            val duration = when (controller.motionPreference) {
                "off" -> 0
                "fast" -> 110
                "soft" -> 260
                else -> 180
            }
            Crossfade(
                targetState = controller.section,
                animationSpec = tween(durationMillis = duration),
                label = "page"
            ) { target ->
                PageContent(controller, target)
            }
        }
    }
}

@Composable
private fun Sidebar(controller: AppController) {
    val sidebarColor = if (controller.darkTheme) {
        Color(0xFF121920)
    } else {
        Color(0xFFF7F8FA)
    }
    Column(
        modifier = Modifier
            .width(238.dp)
            .fillMaxHeight()
            .background(sidebarColor)
            .padding(14.dp)
    ) {
        Brand(controller)
        Spacer(Modifier.height(18.dp))
        LazyColumn(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(4.dp)
        ) {
            NavGroup.entries.forEach { group ->
                item {
                    SectionCaption(group.title, Modifier.padding(top = 12.dp, bottom = 6.dp))
                }
                items(Section.entries.filter { it.group == group }) { section ->
                    NavigationRow(
                        section = section,
                        active = controller.section == section ||
                            (controller.section == Section.WORKSPACE && section == Section.TASKS),
                        badge = if (section == Section.TASKS && controller.sessions.isNotEmpty()) {
                            controller.sessions.size.toString()
                        } else {
                            null
                        },
                        onClick = { controller.navigate(section) }
                    )
                }
            }
        }
        SidebarStatus(controller)
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun Brand(controller: AppController) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 6.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Box(
            modifier = Modifier.size(38.dp).clip(RoundedCornerShape(10.dp))
                .background(SaltTheme.colors.highlight.copy(alpha = 0.12f)),
            contentAlignment = Alignment.Center
        ) {
            Image(
                painterResource("favicon.png"),
                contentDescription = "SpiritScout",
                modifier = Modifier.fillMaxSize(),
                contentScale = ContentScale.Crop
            )
        }
        Column(Modifier.weight(1f)) {
            LocalizedText("灵枢", fontWeight = FontWeight.Bold, fontSize = 17.sp)
            LocalizedText(
                "SpiritScout",
                style = SaltTheme.textStyles.sub,
                color = SaltTheme.colors.subText
            )
        }
        Box(
            modifier = Modifier.size(8.dp).clip(RoundedCornerShape(50))
                .background(if (controller.backendUrl.isNotBlank()) SaltTheme.colors.success else SaltTheme.colors.error)
        )
    }
}

@Composable
private fun NavigationRow(
    section: Section,
    active: Boolean,
    badge: String?,
    onClick: () -> Unit
) {
    val background = if (active) SaltTheme.colors.highlight.copy(alpha = 0.13f) else Color.Transparent
    val foreground = if (active) SaltTheme.colors.highlight else SaltTheme.colors.text
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(9.dp))
            .background(background)
            .clickable(onClick = onClick)
            .padding(horizontal = 11.dp, vertical = 9.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(11.dp)
    ) {
        Icon(section.icon, section.title, modifier = Modifier.size(18.dp), tint = foreground)
        LocalizedText(
            section.title,
            modifier = Modifier.weight(1f),
            color = foreground,
            fontWeight = if (active) FontWeight.SemiBold else FontWeight.Normal,
            maxLines = 1
        )
        badge?.let {
            Box(
                modifier = Modifier
                    .clip(RoundedCornerShape(50))
                    .background(SaltTheme.colors.highlight.copy(alpha = if (active) 0.18f else 0.09f))
                    .padding(horizontal = 7.dp, vertical = 2.dp)
            ) {
                LocalizedText(it, style = SaltTheme.textStyles.sub, color = foreground)
            }
        }
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun SidebarStatus(controller: AppController) {
    val system = controller.system
    Card(
        modifier = Modifier.fillMaxWidth().padding(top = 10.dp),
        color = SaltTheme.colors.subBackground
    ) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(7.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Icon(
                    if (controller.backendUrl.isNotBlank()) Icons.Outlined.CheckCircle else Icons.Outlined.CloudOff,
                    null,
                    modifier = Modifier.size(16.dp),
                    tint = if (controller.backendUrl.isNotBlank()) SaltTheme.colors.success else SaltTheme.colors.error
                )
                LocalizedText(
                    if (controller.backendUrl.isNotBlank()) "本机控制台在线" else "控制台离线",
                    style = SaltTheme.textStyles.sub,
                    color = SaltTheme.colors.subText
                )
            }
            LocalizedText(
                "CPU ${"%.0f".format(system?.cpu ?: 0.0)}% · 内存 ${"%.0f".format(system?.memory ?: 0.0)}%",
                style = SaltTheme.textStyles.sub,
                color = SaltTheme.colors.subText
            )
        }
    }
}
