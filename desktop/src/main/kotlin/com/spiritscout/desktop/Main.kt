package com.spiritscout.desktop

import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.width
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.ExperimentalComposeUiApi
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.DpSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.WindowPosition
import androidx.compose.ui.window.application
import androidx.compose.ui.window.rememberWindowState
import com.moriafly.salt.ui.SaltConfigs
import com.moriafly.salt.ui.SaltTheme
import com.moriafly.salt.ui.UnstableSaltUiApi
import com.moriafly.salt.ui.window.CaptionBarHitTest
import com.moriafly.salt.ui.window.DesktopCaptionBar
import com.moriafly.salt.ui.window.LocalSaltWindowInfo
import com.moriafly.salt.ui.window.SaltWindow
import com.moriafly.salt.ui.window.SaltWindowBackgroundType
import com.moriafly.salt.ui.window.SaltWindowProperties
import com.spiritscout.desktop.ui.SpiritScoutRoot
import com.spiritscout.desktop.ui.DesktopI18n
import com.spiritscout.desktop.ui.LocalizedText
import com.spiritscout.desktop.model.Section
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.launch
import java.awt.dnd.DnDConstants
import java.awt.dnd.DropTarget
import java.awt.dnd.DropTargetAdapter
import java.awt.dnd.DropTargetDragEvent
import java.awt.dnd.DropTargetDropEvent
import java.awt.datatransfer.DataFlavor
import java.io.File

@OptIn(ExperimentalComposeUiApi::class, UnstableSaltUiApi::class)
fun main() = application {
    val controller = remember { AppController() }
    val closeScope = rememberCoroutineScope()

    LaunchedEffect(Unit) {
        controller.bootstrap()
    }

    SaltTheme(configs = SaltConfigs.default(isDarkTheme = controller.darkTheme)) {
        SaltWindow(
            onCloseRequest = {
                closeScope.launch(NonCancellable) {
                    controller.shutdown()
                    exitApplication()
                }
            },
            state = rememberWindowState(
                size = DpSize(1420.dp, 900.dp),
                position = WindowPosition.Aligned(Alignment.Center)
            ),
            title = DesktopI18n.translate("灵枢 · SpiritScout"),
            icon = painterResource("favicon.png"),
            resizable = true,
            properties = SaltWindowProperties.default(
                captionButtonIsDarkTheme = controller.darkTheme,
                backgroundType = when {
                    SaltWindowBackgroundType.Mica.isSupported() -> SaltWindowBackgroundType.Mica
                    SaltWindowBackgroundType.Vibrancy.isSupported() -> SaltWindowBackgroundType.Vibrancy
                    else -> SaltWindowBackgroundType.None
                },
                backgroundIsDarkTheme = controller.darkTheme
            )
        ) {
            DisposableEffect(window, controller.section, controller.selectedSession?.id) {
                val listener = object : DropTargetAdapter() {
                    override fun dragEnter(event: DropTargetDragEvent) {
                        if (controller.section == Section.WORKSPACE &&
                            controller.selectedSession != null &&
                            event.transferable.isDataFlavorSupported(DataFlavor.javaFileListFlavor)
                        ) {
                            event.acceptDrag(DnDConstants.ACTION_COPY)
                        } else {
                            event.rejectDrag()
                        }
                    }

                    override fun drop(event: DropTargetDropEvent) {
                        if (controller.section != Section.WORKSPACE ||
                            controller.selectedSession == null ||
                            !event.transferable.isDataFlavorSupported(DataFlavor.javaFileListFlavor)
                        ) {
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
                            files.filter(File::isDirectory).forEach {
                                controller.addFolderUploads(it.toPath())
                            }
                            event.dropComplete(true)
                        } catch (_: Exception) {
                            event.dropComplete(false)
                        }
                    }
                }
                val target = DropTarget(window, DnDConstants.ACTION_COPY, listener, true)
                onDispose { target.removeDropTargetListener(listener) }
            }
            SpiritScoutRoot(
                controller = controller,
                captionBarHeight = LocalSaltWindowInfo.current.captionBarHeight
            )

            DesktopCaptionBar {
                Row(
                    modifier = Modifier.fillMaxSize(),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Spacer(Modifier.width(14.dp))
                    LocalizedText(
                        if (controller.backendUrl.isBlank()) {
                            "灵枢 · SpiritScout"
                        } else {
                            "灵枢 · SpiritScout  /  ${controller.backendUrl}"
                        }
                    )
                }
            }
            CaptionBarHitTest()
        }
    }
}
