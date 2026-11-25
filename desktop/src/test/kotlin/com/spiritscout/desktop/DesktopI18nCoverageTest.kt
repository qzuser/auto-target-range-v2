package com.spiritscout.desktop

import com.spiritscout.desktop.ui.DesktopI18n
import java.io.File
import kotlin.test.AfterTest
import kotlin.test.Test
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class DesktopI18nCoverageTest {
    @AfterTest
    fun restoreChinese() {
        DesktopI18n.applyLanguage("zh-CN")
    }

    @Test
    fun `every static Chinese UI string has an English translation`() {
        DesktopI18n.applyLanguage("en-US")
        val sourceDir = File("src/main/kotlin/com/spiritscout/desktop")
        assertTrue(sourceDir.isDirectory, "Desktop source directory not found: ${sourceDir.absolutePath}")

        val chineseString = Regex("\"([^\"\\r\\n]*[\\p{IsHan}][^\"\\r\\n]*)\"")
        val values = sourceDir.walkTopDown()
            .filter { file -> file.isFile && file.extension == "kt" }
            .flatMap { file ->
                chineseString.findAll(file.readText())
                    .map { it.groupValues[1] }
                    .filterNot { it.contains('$') }
                    .toList()
            }
            .toSet()

        val missing = values.filter { source ->
            DesktopI18n.translate(source) == source
        }
        val stillChinese = values.mapNotNull { source ->
            val translated = DesktopI18n.translate(source)
            if (translated.contains(Regex("[\\p{IsHan}]"))) {
                "$source -> $translated"
            } else {
                null
            }
        }

        assertTrue(values.isNotEmpty(), "No Chinese UI strings were discovered")
        assertTrue(
            missing.isEmpty(),
            "Missing English desktop UI translations (${missing.size}):\n" +
                missing.sorted().joinToString("\n")
        )
        assertFalse(
            stillChinese.isNotEmpty(),
            "English translations still contain Chinese (${stillChinese.size}):\n" +
                stillChinese.sorted().joinToString("\n")
        )
    }
}
