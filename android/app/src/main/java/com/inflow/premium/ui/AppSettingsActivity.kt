package com.inflow.premium.ui

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.view.KeyEvent
import android.view.View
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.inflow.premium.MainActivity
import com.inflow.premium.data.ApiClient
import com.inflow.premium.data.SessionManager
import com.inflow.premium.databinding.ActivityAppSettingsBinding
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import java.text.DecimalFormat

class AppSettingsActivity : AppCompatActivity() {

    private lateinit var binding: ActivityAppSettingsBinding
    private lateinit var session: SessionManager
    private lateinit var api: ApiClient
    private val uiScope = CoroutineScope(Dispatchers.Main + SupervisorJob())

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        session = SessionManager(this)
        if (!session.isLoggedIn()) {
            redirectToLogin()
            return
        }

        binding = ActivityAppSettingsBinding.inflate(layoutInflater)
        setContentView(binding.root)
        api = ApiClient(session)

        BottomNavHelper.setup(this, binding.bottomNav.root, BottomNavHelper.NavTab.SETTINGS)

        bindInfo()

        binding.btnSettingBranch.visibility = if (session.isMainAdmin()) View.VISIBLE else View.GONE
        binding.btnSettingBranch.setOnClickListener { showBranchPicker() }

        binding.btnSettingSync.setOnClickListener {
            binding.btnSettingSync.isEnabled = false
            uiScope.launch {
                try {
                    api.bootstrap()
                    bindInfo()
                    Toast.makeText(this@AppSettingsActivity, "Metadata synced successfully", Toast.LENGTH_SHORT).show()
                } catch (e: Exception) {
                    Toast.makeText(this@AppSettingsActivity, e.message ?: "Sync failed", Toast.LENGTH_SHORT).show()
                } finally {
                    binding.btnSettingSync.isEnabled = true
                }
            }
        }

        binding.btnOpenWebPortal.setOnClickListener {
            startActivity(
                Intent(this, MainActivity::class.java)
                    .putExtra("extra_url", api.buildWebPortalUrl("/"))
            )
        }

        binding.btnOpenWebSettings.setOnClickListener {
            startActivity(
                Intent(this, MainActivity::class.java)
                    .putExtra("extra_url", api.buildWebPortalUrl("/settings"))
            )
        }

        binding.btnCheckUpdate.setOnClickListener {
            startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("${session.baseUrl}/download-app")))
        }

        binding.btnSignOut.setOnClickListener { confirmSignOut() }
    }

    override fun onResume() {
        super.onResume()
        if (::session.isInitialized) {
            bindInfo()
        }
    }

    private fun bindInfo() {
        val name = session.getDisplayName().ifBlank { session.getUsername() }
        val branchKey = session.selectedBranch
        val branchLabel = when {
            branchKey == "all" -> "All Branches"
            branchKey == "main" || branchKey == "0" -> "Main Store (HQ)"
            else -> session.getBranches().firstOrNull { it.id == branchKey }?.name ?: "Branch #$branchKey"
        }
        binding.tvSettingUser.text = "$name (@${session.getUsername()})"
        binding.tvSettingRole.text = "Active Store: $branchLabel"
        binding.tvSettingServer.text = "Server: ${session.baseUrl}"
        val df = DecimalFormat("#,##0")
        binding.tvSettingRate.text = "Default KHR Rate: ${df.format(Math.round(session.defaultKhrRate))} KHR"
    }

    private fun showBranchPicker() {
        val options = mutableListOf<Pair<String, String>>()
        options.add("main" to "Main Store (HQ)")
        for (b in session.getBranches()) {
            if (b.id != "0" && b.id != "main") {
                options.add(b.id to b.name)
            }
        }
        options.add("all" to "All Branches")

        val labels = options.map { it.second }.toTypedArray()
        val checkedIdx = options.indexOfFirst { it.first == session.selectedBranch }.coerceAtLeast(0)

        val dlg = MaterialAlertDialogBuilder(this)
            .setTitle("Default Active Store / Branch")
            .setSingleChoiceItems(labels, checkedIdx) { dialog, which ->
                session.selectedBranch = options[which].first
                bindInfo()
                dialog.dismiss()
                Toast.makeText(this, "Switched to ${options[which].second}", Toast.LENGTH_SHORT).show()
            }
            .setNegativeButton("Close") { d, _ -> d.dismiss() }
            .setCancelable(false)
            .create()
        attachEscClose(dlg)
        dlg.setCanceledOnTouchOutside(false)
        dlg.show()
    }

    private fun confirmSignOut() {
        val dlg = MaterialAlertDialogBuilder(this)
            .setTitle("Sign Out")
            .setMessage("Sign out of ${session.getDisplayName().ifBlank { session.getUsername() }}?")
            .setPositiveButton("Sign Out") { _, _ -> redirectToLogin() }
            .setNegativeButton("Cancel") { d, _ -> d.dismiss() }
            .setCancelable(false)
            .create()
        attachEscClose(dlg)
        dlg.setCanceledOnTouchOutside(false)
        dlg.show()
    }

    private fun attachEscClose(dialog: AlertDialog) {
        dialog.setOnKeyListener { d, keyCode, event ->
            if (event.action == KeyEvent.ACTION_UP &&
                (keyCode == KeyEvent.KEYCODE_ESCAPE || keyCode == KeyEvent.KEYCODE_BACK)
            ) {
                d.dismiss()
                true
            } else {
                false
            }
        }
    }

    private fun redirectToLogin() {
        session.logout()
        startActivity(Intent(this, LoginActivity::class.java))
        finish()
    }

    override fun onDestroy() {
        super.onDestroy()
        uiScope.cancel()
    }
}
