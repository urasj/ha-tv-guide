package com.urasj.tvguidehelper

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.provider.Settings
import android.view.Gravity
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView

class MainActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        startService(Intent(this, ServerService::class.java))

        val root = LinearLayout(this)
        root.orientation = LinearLayout.VERTICAL
        root.gravity = Gravity.CENTER
        root.setPadding(80, 80, 80, 80)

        val title = TextView(this)
        title.textSize = 26f
        title.text = "TV Guide Helper"

        val body = TextView(this)
        body.textSize = 18f
        body.text = "Command server is running on port 8472.\n\n" +
            "One-time setup: enable the accessibility service so the helper can read the screen and tap profiles."

        val btn = Button(this)
        btn.text = "Open accessibility settings"
        btn.setOnClickListener {
            try { startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)) } catch (_: Exception) {}
        }

        root.addView(title)
        root.addView(body)
        root.addView(btn)
        setContentView(root)
    }
}
