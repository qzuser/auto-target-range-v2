package com.spiritscout.desktop.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.moriafly.salt.ui.SaltTheme
import com.moriafly.salt.ui.Text
import com.moriafly.salt.ui.UnstableSaltUiApi

@OptIn(UnstableSaltUiApi::class)
@Composable
fun MarkdownView(content: String, modifier: Modifier = Modifier) {
    val lines = content.replace("\r\n", "\n").split('\n')
    var index = 0
    Column(
        modifier = modifier.verticalScroll(rememberScrollState()).padding(4.dp),
        verticalArrangement = Arrangement.spacedBy(7.dp)
    ) {
        while (index < lines.size) {
            val line = lines[index]
            when {
                line.startsWith("```") -> {
                    val language = line.removePrefix("```").trim()
                    val code = buildString {
                        index++
                        while (index < lines.size && !lines[index].startsWith("```")) {
                            if (isNotEmpty()) append('\n')
                            append(lines[index])
                            index++
                        }
                    }
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(8.dp))
                            .background(SaltTheme.colors.subBackground)
                            .padding(12.dp)
                    ) {
                        if (language.isNotBlank()) {
                            LocalizedText(
                                language,
                                style = SaltTheme.textStyles.sub,
                                color = SaltTheme.colors.subText
                            )
                            Spacer(Modifier.height(5.dp))
                        }
                        SelectionContainer {
                            LocalizedText(
                                code.ifBlank { " " },
                                fontFamily = FontFamily.Monospace,
                                style = SaltTheme.textStyles.sub
                            )
                        }
                    }
                }
                line.startsWith("#### ") -> MarkdownHeading(line.removePrefix("#### "), 4)
                line.startsWith("### ") -> MarkdownHeading(line.removePrefix("### "), 3)
                line.startsWith("## ") -> MarkdownHeading(line.removePrefix("## "), 2)
                line.startsWith("# ") -> MarkdownHeading(line.removePrefix("# "), 1)
                line.startsWith("> ") -> LocalizedText(
                    line.removePrefix("> "),
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(6.dp))
                        .background(SaltTheme.colors.subBackground)
                        .padding(10.dp),
                    style = SaltTheme.textStyles.paragraph,
                    color = SaltTheme.colors.subText
                )
                line.matches(Regex("^-{3,}$")) || line.matches(Regex("^\\*{3,}$")) -> {
                    Spacer(
                        Modifier
                            .fillMaxWidth()
                            .height(1.dp)
                            .background(SaltTheme.colors.stroke)
                    )
                }
                line.startsWith("- ") || line.startsWith("* ") -> MarkdownBullet(line.drop(2))
                line.matches(Regex("^\\d+\\.\\s+.*")) -> {
                    val number = line.substringBefore('.').ifBlank { "•" }
                    MarkdownBullet(line.substringAfter('.').trim(), number)
                }
                line.isBlank() -> Spacer(Modifier.height(3.dp))
                else -> SelectionContainer {
                    LocalizedText(
                        stripInlineMarkdown(line),
                        style = SaltTheme.textStyles.paragraph
                    )
                }
            }
            index++
        }
    }
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun MarkdownHeading(text: String, level: Int) {
    LocalizedText(
        stripInlineMarkdown(text),
        style = when (level) {
            1 -> SaltTheme.textStyles.largeTitle
            2 -> SaltTheme.textStyles.main
            else -> SaltTheme.textStyles.paragraph
        },
        fontWeight = FontWeight.SemiBold
    )
}

@OptIn(UnstableSaltUiApi::class)
@Composable
private fun MarkdownBullet(text: String, marker: String = "•") {
    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        LocalizedText(marker, color = SaltTheme.colors.highlight, fontWeight = FontWeight.SemiBold)
        SelectionContainer {
            LocalizedText(stripInlineMarkdown(text), style = SaltTheme.textStyles.paragraph)
        }
    }
}

private fun stripInlineMarkdown(text: String): String =
    text.replace(Regex("!\\[([^]]*)]\\([^)]*\\)"), "$1")
        .replace(Regex("\\[([^]]+)]\\([^)]*\\)"), "$1")
        .replace(Regex("`([^`]+)`"), "$1")
        .replace("**", "")
        .replace("__", "")
        .replace("*", "")
        .replace("_", "")
