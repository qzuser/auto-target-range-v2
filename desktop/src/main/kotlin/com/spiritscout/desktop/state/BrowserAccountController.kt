package com.spiritscout.desktop.state

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.spiritscout.desktop.model.array
import com.spiritscout.desktop.model.boolean
import com.spiritscout.desktop.model.int
import com.spiritscout.desktop.model.long
import com.spiritscout.desktop.model.objectOrEmpty
import com.spiritscout.desktop.model.string
import com.spiritscout.desktop.service.SpiritApi
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.net.URLEncoder
import java.nio.charset.StandardCharsets

data class BrowserAccountRow(
    val id: String,
    val name: String,
    val role: String,
    val origins: List<String>,
    val retain: Boolean,
    val ttlDays: Int,
    val cacheStatus: String,
    val cookieCount: Int,
    val originCount: Int,
    val usernameHint: String,
    val credentialsConfigured: Boolean,
    val mfaMethod: String,
    val mfaDestinationHint: String,
    val opened: Boolean,
    val version: Long
)

class BrowserAccountController(
    private val apiProvider: () -> SpiritApi?,
    private val scope: CoroutineScope
) {
    val accounts = mutableStateListOf<BrowserAccountRow>()
    var loading by mutableStateOf(false)
        private set
    var saving by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set
    var message by mutableStateOf("")
        private set

    fun refresh() {
        val currentApi = apiProvider() ?: return
        scope.launch {
            loading = true
            error = null
            try {
                accounts.clear()
                accounts += currentApi.get("/api/browser-accounts").array("items").map { raw ->
                    val item = raw.objectOrEmpty()
                    BrowserAccountRow(
                        id = item.string("id"),
                        name = item.string("name"),
                        role = item.string("role"),
                        origins = item.array("origins").map { it.toString().trim('"') },
                        retain = item.boolean("retain"),
                        ttlDays = item.int("ttl_days"),
                        cacheStatus = item.string("cache_status"),
                        cookieCount = item.int("cookie_count"),
                        originCount = item.int("origin_count"),
                        usernameHint = item.string("username_hint"),
                        credentialsConfigured = item.boolean("credentials_configured"),
                        mfaMethod = item.string("mfa_method"),
                        mfaDestinationHint = item.string("mfa_destination_hint"),
                        opened = item.boolean("opened"),
                        version = item.long("version")
                    )
                }
            } catch (failure: Exception) {
                error = failure.message ?: "浏览器账号读取失败"
            } finally {
                loading = false
            }
        }
    }

    fun save(
        original: BrowserAccountRow?,
        key: String,
        name: String,
        role: String,
        originsText: String,
        retain: Boolean,
        ttlDaysText: String,
        username: String,
        password: String,
        mfaMethod: String,
        mfaDestination: String,
        clearCredentials: Boolean = false
    ) {
        val currentApi = apiProvider() ?: return
        if (key.isBlank() || name.isBlank()) {
            error = "账号标识和名称不能为空。"
            return
        }
        val origins = originsText.lines().map(String::trim).filter(String::isNotBlank)
        if (origins.isEmpty()) {
            error = "至少填写一个账号网站地址。"
            return
        }
        scope.launch {
            saving = true
            error = null
            try {
                val data = buildJsonObject {
                    put("name", name.trim())
                    put("role", role.trim())
                    put("origins", JsonArray(origins.map(::JsonPrimitive)))
                    put("retain", retain)
                    put("ttl_days", ttlDaysText.toIntOrNull()?.coerceAtLeast(1) ?: 7)
                    put("mfa_method", mfaMethod)
                    put("mfa_destination", mfaDestination.trim())
                    if (username.isNotBlank()) put("username", username.trim())
                    if (password.isNotBlank()) put("password", password)
                    if (clearCredentials) put("clear_credentials", true)
                }
                currentApi.put(
                    "/api/browser-accounts/${enc(key)}",
                    buildJsonObject {
                        put("data", data)
                        put("expected_version", original?.version ?: 0)
                    }.toString()
                )
                message = "浏览器账号已保存"
                refresh()
            } catch (failure: Exception) {
                error = failure.message ?: "浏览器账号保存失败"
            } finally {
                saving = false
            }
        }
    }

    fun action(account: BrowserAccountRow, action: String) {
        val currentApi = apiProvider() ?: return
        scope.launch {
            saving = true
            error = null
            try {
                currentApi.post(
                    "/api/browser-accounts/${enc(account.id)}/${enc(action)}",
                    buildJsonObject { put("expected_version", account.version) }.toString()
                )
                message = when (action) {
                    "open" -> "已打开账号浏览器"
                    "capture" -> "登录态已保存"
                    "close" -> "账号浏览器已关闭"
                    "clear" -> "账号缓存已清理"
                    "delete" -> "账号已删除"
                    else -> "操作已完成"
                }
                refresh()
            } catch (failure: Exception) {
                error = failure.message ?: "浏览器账号操作失败"
            } finally {
                saving = false
            }
        }
    }

    private fun enc(value: String): String =
        URLEncoder.encode(value, StandardCharsets.UTF_8)
}
