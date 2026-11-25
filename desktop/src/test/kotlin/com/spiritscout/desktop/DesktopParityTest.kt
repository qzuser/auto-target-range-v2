package com.spiritscout.desktop

import com.spiritscout.desktop.model.Section
import com.spiritscout.desktop.model.WorkspaceTab
import kotlin.test.Test
import kotlin.test.assertTrue

class DesktopParityTest {
    @Test
    fun `all web navigation modules remain available`() {
        val expected = setOf(
            Section.TASKS,
            Section.PROJECTS,
            Section.ASSETS,
            Section.DASHBOARD,
            Section.SCHEDULES,
            Section.AGENTS,
            Section.MODELS,
            Section.MCP,
            Section.SKILLS,
            Section.LOCAL_TOOLS,
            Section.EXPERIENCE,
            Section.INTELLIGENCE,
            Section.PROXIES,
            Section.BROWSER_ACCOUNTS,
            Section.TRAFFIC,
            Section.SETTINGS
        )
        assertTrue(Section.entries.containsAll(expected))
    }

    @Test
    fun `session workspace covers the web result views`() {
        val expected = setOf(
            WorkspaceTab.CHAT,
            WorkspaceTab.FILES,
            WorkspaceTab.TOPOLOGY,
            WorkspaceTab.ASSETS,
            WorkspaceTab.OPPORTUNITIES,
            WorkspaceTab.CHALLENGES,
            WorkspaceTab.VULNERABILITIES,
            WorkspaceTab.FLAGS,
            WorkspaceTab.EXPERIENCE,
            WorkspaceTab.TRAFFIC,
            WorkspaceTab.BACKGROUND,
            WorkspaceTab.EVENTS,
            WorkspaceTab.RECORDS,
            WorkspaceTab.DELIVERABLES,
            WorkspaceTab.REPORT
        )
        assertTrue(WorkspaceTab.entries.containsAll(expected))
    }
}
