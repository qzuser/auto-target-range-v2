package com.spiritscout.desktop

import com.spiritscout.desktop.model.SessionItem
import com.spiritscout.desktop.model.WorkspaceTab
import com.spiritscout.desktop.model.objectOrEmpty
import com.spiritscout.desktop.model.string
import com.spiritscout.desktop.ui.workspaceItems
import kotlinx.serialization.json.Json
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class WorkspaceBehaviorTest {
    @Test
    fun `side session metadata survives session parsing`() {
        val session = SessionItem.fromJson(
            Json.parseToJsonElement(
                """
                {
                  "session_id": "side-1",
                  "title": "旁路",
                  "mode": "src",
                  "status": "running",
                  "side_session": {
                    "parent_session_id": "parent-1",
                    "agent": "web-pentester",
                    "task_id": "task-1"
                  }
                }
                """.trimIndent()
            )
        )

        assertTrue(session.isSideSession)
        assertEquals("parent-1", session.sideParentId)
        assertEquals("web-pentester", session.sideAgent)
        assertEquals("task-1", session.sideTaskId)
    }

    @Test
    fun `workspace domain extraction unwraps nested topology and flag collections`() {
        val topology = Json.parseToJsonElement(
            """{"topology":{"nodes":[{"id":"node-1","title":"入口"},{"id":"node-2"}]}}"""
        )
        val flags = Json.parseToJsonElement(
            """{"flags":{"items":[{"value":"flag{a}","status":"accepted"}]}}"""
        )

        assertEquals(2, workspaceItems(WorkspaceTab.TOPOLOGY, topology).size)
        assertEquals(1, workspaceItems(WorkspaceTab.FLAGS, flags).size)
        assertEquals(
            "flag{a}",
            workspaceItems(WorkspaceTab.FLAGS, flags).single()
                .objectOrEmpty()
                .string("value")
        )
    }
}
