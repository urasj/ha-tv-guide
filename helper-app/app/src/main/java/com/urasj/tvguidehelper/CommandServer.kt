package com.urasj.tvguidehelper

import android.content.Context
import android.content.Intent
import android.net.Uri
import fi.iki.elonen.NanoHTTPD
import org.json.JSONObject

class CommandServer(private val ctx: Context, port: Int) : NanoHTTPD(port) {

    override fun serve(session: IHTTPSession): Response {
        val uri = session.uri.trimEnd('/')
        val json = parse(session)
        return try {
            when {
                uri.endsWith("/ping") -> ok(
                    JSONObject()
                        .put("ok", true)
                        .put("app", "tvguide-helper")
                        .put("version", "1.0")
                        .put("accessibility", HelperAccessibilityService.isEnabled())
                        .put("foreground", HelperAccessibilityService.currentPackage())
                )
                uri.endsWith("/foreground") -> ok(
                    JSONObject().put("foreground", HelperAccessibilityService.currentPackage())
                )
                uri.endsWith("/launch") -> {
                    launch(json.optString("package"), json.optString("deep_link", ""))
                    ok(JSONObject().put("ok", true))
                }
                uri.endsWith("/deeplink") -> {
                    deeplink(json.optString("package"), json.optString("url"))
                    ok(JSONObject().put("ok", true))
                }
                uri.endsWith("/screen") -> ok(HelperAccessibilityService.dumpScreen())
                uri.endsWith("/click") || uri.endsWith("/selectprofile") -> {
                    val q = json.optString("text", json.optString("name", ""))
                    val found = HelperAccessibilityService.clickByText(q)
                    ok(JSONObject().put("ok", found).put("clicked", found).put("query", q))
                }
                uri.endsWith("/global") -> {
                    HelperAccessibilityService.globalAction(json.optString("action"))
                    ok(JSONObject().put("ok", true))
                }
                else -> newFixedLengthResponse(
                    Response.Status.NOT_FOUND, "application/json", "{\"error\":\"unknown endpoint\"}"
                )
            }
        } catch (e: Exception) {
            newFixedLengthResponse(
                Response.Status.INTERNAL_ERROR, "application/json",
                JSONObject().put("error", e.message ?: "error").toString()
            )
        }
    }

    private fun parse(session: IHTTPSession): JSONObject {
        return try {
            val map = HashMap<String, String>()
            session.parseBody(map)
            JSONObject(map["postData"] ?: "{}")
        } catch (e: Exception) {
            JSONObject()
        }
    }

    private fun ok(payload: Any): Response =
        newFixedLengthResponse(Response.Status.OK, "application/json", payload.toString())

    private fun launch(pkg: String, deepLink: String) {
        if (pkg.isBlank()) return
        if (deepLink.isNotBlank()) { deeplink(pkg, deepLink); return }
        val intent = ctx.packageManager.getLeanbackLaunchIntentForPackage(pkg)
            ?: ctx.packageManager.getLaunchIntentForPackage(pkg)
        if (intent != null) {
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            ctx.startActivity(intent)
        }
    }

    private fun deeplink(pkg: String, url: String) {
        if (url.isBlank()) return
        val intent = Intent(Intent.ACTION_VIEW, Uri.parse(url))
        if (pkg.isNotBlank()) intent.setPackage(pkg)
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        ctx.startActivity(intent)
    }
}
