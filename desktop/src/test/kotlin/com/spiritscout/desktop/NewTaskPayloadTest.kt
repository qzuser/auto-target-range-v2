package com.spiritscout.desktop

import com.spiritscout.desktop.model.NewTaskRequest
import com.spiritscout.desktop.model.toPayloadJson
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonPrimitive
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

class NewTaskPayloadTest {
    @Test
    fun `task payload preserves web contract and selected asset handoff`() {
        val request = NewTaskRequest(
            title = "SRC checkpoint",
            mode = "src",
            target = "manual.example",
            mission = "test selected assets",
            scope = listOf("manual.example", "selected.example"),
            model = "model-a",
            uploadIds = listOf("file-1"),
            generateWriteup = true,
            allowSensitive = true,
            projectId = "prj-1",
            proxyPlanId = "proxy-abc123def456",
            assetStrategy = "balanced",
            assetCampaignId = "campaign-1",
            assetValues = listOf("selected.example", "second.example", "selected.example"),
            excludedAssets = listOf("excluded.example", "excluded.example"),
            platform = "judge",
            flagFormat = "flag{...}",
            multipleAnswers = true,
            ctfTypeHints = listOf("Web", "Web"),
            ctfTypeNote = "note",
            challengesYaml = "challenges: []",
            platformYaml = "platform: judge",
            rulesYaml = "rules: []",
            contestType = "jeopardy",
            budgetTokens = 1200,
            rps = 4.5,
            noLlm = true,
            acceptRuleConflicts = true,
            browserAccountIds = listOf("account-1")
        )

        val payload = request.toPayloadJson(listOf("folder-1", "file-1"))

        assertEquals("selected.example", payload.getValue("target").jsonPrimitive.content)
        assertEquals(
            listOf("manual.example", "selected.example", "second.example"),
            payload.getValue("scope").jsonArray.map { it.jsonPrimitive.content }
        )
        assertEquals("campaign-1", payload.getValue("asset_campaign_id").jsonPrimitive.content)
        assertEquals(
            listOf("selected.example", "second.example"),
            payload.getValue("asset_values").jsonArray.map { it.jsonPrimitive.content }
        )
        assertEquals(
            listOf("excluded.example"),
            payload.getValue("excluded_assets").jsonArray.map { it.jsonPrimitive.content }
        )
        assertEquals(
            listOf("file-1", "folder-1"),
            payload.getValue("upload_ids").jsonArray.map { it.jsonPrimitive.content }
        )
        assertEquals(
            listOf("account-1"),
            payload.getValue("browser_account_ids").jsonArray.map { it.jsonPrimitive.content }
        )
        assertEquals("challenges: []", payload.getValue("challenges_yaml").jsonPrimitive.content)
        assertEquals("platform: judge", payload.getValue("platform_yaml").jsonPrimitive.content)
        assertEquals(1200, payload.getValue("budget_tokens").jsonPrimitive.content.toInt())
        assertEquals(true, payload.getValue("accept_rule_conflicts").jsonPrimitive.content.toBoolean())
    }

    @Test
    fun `manual target remains authoritative without asset selection`() {
        val payload = NewTaskRequest(
            title = "",
            mode = "ctf",
            target = "https://challenge.example",
            mission = "solve",
            scope = listOf("https://challenge.example"),
            model = ""
        ).toPayloadJson()

        assertEquals("https://challenge.example", payload.getValue("target").jsonPrimitive.content)
        assertTrue(payload.getValue("asset_values").jsonArray.isEmpty())
        assertNull(payload.getValue("challenges_yaml").jsonPrimitive.contentOrNull)
    }
}
