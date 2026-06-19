package com.urasj.tvguidehelper

import android.accessibilityservice.AccessibilityService
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import org.json.JSONArray
import org.json.JSONObject

class HelperAccessibilityService : AccessibilityService() {

    override fun onServiceConnected() {
        super.onServiceConnected()
        instance = this
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        if (event?.eventType == AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED) {
            event.packageName?.let { lastPackage = it.toString() }
        }
    }

    override fun onInterrupt() {}

    override fun onDestroy() {
        if (instance === this) instance = null
        super.onDestroy()
    }

    companion object {
        @Volatile private var instance: HelperAccessibilityService? = null
        @Volatile var lastPackage: String = ""

        fun isEnabled(): Boolean = instance != null
        fun currentPackage(): String = lastPackage

        fun globalAction(name: String) {
            val service = instance ?: return
            val action = when (name) {
                "home" -> GLOBAL_ACTION_HOME
                "back" -> GLOBAL_ACTION_BACK
                "recents" -> GLOBAL_ACTION_RECENTS
                else -> -1
            }
            if (action >= 0) service.performGlobalAction(action)
        }

        fun dumpScreen(): JSONObject {
            val service = instance ?: return JSONObject().put("error", "accessibility not enabled")
            val root = service.rootInActiveWindow
                ?: return JSONObject().put("error", "no active window").put("package", lastPackage)
            val nodes = JSONArray()
            collect(root, nodes, 0)
            return JSONObject()
                .put("package", root.packageName?.toString() ?: lastPackage)
                .put("nodes", nodes)
        }

        private fun collect(node: AccessibilityNodeInfo?, out: JSONArray, depth: Int) {
            if (node == null || depth > 60) return
            val text = node.text?.toString()
            val desc = node.contentDescription?.toString()
            if (!text.isNullOrBlank() || !desc.isNullOrBlank()) {
                out.put(
                    JSONObject()
                        .put("text", text ?: "")
                        .put("desc", desc ?: "")
                        .put("clickable", node.isClickable)
                        .put("focused", node.isFocused || node.isAccessibilityFocused)
                )
            }
            for (i in 0 until node.childCount) collect(node.getChild(i), out, depth + 1)
        }

        fun clickByText(query: String?): Boolean {
            val service = instance ?: return false
            if (query.isNullOrBlank()) return false
            val root = service.rootInActiveWindow ?: return false
            val match = find(root, query.lowercase()) ?: return false
            var node: AccessibilityNodeInfo? = match
            while (node != null) {
                if (node.isClickable) {
                    node.performAction(AccessibilityNodeInfo.ACTION_CLICK)
                    return true
                }
                node = node.parent
            }
            match.performAction(AccessibilityNodeInfo.ACTION_CLICK)
            return true
        }

        private fun find(node: AccessibilityNodeInfo?, query: String): AccessibilityNodeInfo? {
            if (node == null) return null
            val text = (node.text?.toString() ?: "").lowercase()
            val desc = (node.contentDescription?.toString() ?: "").lowercase()
            if (text == query || desc == query || text.contains(query) || desc.contains(query)) return node
            for (i in 0 until node.childCount) {
                val result = find(node.getChild(i), query)
                if (result != null) return result
            }
            return null
        }
    }
}
