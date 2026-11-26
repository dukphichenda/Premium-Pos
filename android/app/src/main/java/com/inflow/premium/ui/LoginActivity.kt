package com.inflow.premium.ui

import android.content.Intent
import android.os.Bundle
import android.view.View
import android.view.inputmethod.EditorInfo
import androidx.appcompat.app.AppCompatActivity
import com.inflow.premium.data.ApiClient
import com.inflow.premium.data.SessionManager
import com.inflow.premium.databinding.ActivityLoginBinding
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

class LoginActivity : AppCompatActivity() {

    private lateinit var binding: ActivityLoginBinding
    private lateinit var session: SessionManager
    private lateinit var api: ApiClient
    private val uiScope = CoroutineScope(Dispatchers.Main + SupervisorJob())

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        session = SessionManager(this)
        if (session.isLoggedIn()) {
            goToSalesOrders()
            return
        }

        binding = ActivityLoginBinding.inflate(layoutInflater)
        setContentView(binding.root)
        api = ApiClient(session)

        binding.etServerUrl.setText(session.baseUrl)

        binding.tvToggleServer.setOnClickListener {
            val isVisible = binding.tilServerUrl.visibility == View.VISIBLE
            binding.tilServerUrl.visibility = if (isVisible) View.GONE else View.VISIBLE
        }

        binding.etPassword.setOnEditorActionListener { _, actionId, _ ->
            if (actionId == EditorInfo.IME_ACTION_DONE) {
                attemptLogin()
                true
            } else {
                false
            }
        }

        binding.btnSignIn.setOnClickListener { attemptLogin() }
    }

    private fun attemptLogin() {
        val username = binding.etUsername.text?.toString()?.trim().orEmpty()
        val password = binding.etPassword.text?.toString().orEmpty()
        val customUrl = binding.etServerUrl.text?.toString()?.trim().orEmpty()

        if (customUrl.isNotBlank()) {
            session.baseUrl = customUrl
        }

        if (username.isBlank() || password.isBlank()) {
            showError("Please enter both username and password.")
            return
        }

        setLoading(true)
        uiScope.launch {
            try {
                api.login(username, password)
                goToSalesOrders()
            } catch (e: Exception) {
                setLoading(false)
                showError(e.message ?: "Unable to sign in")
            }
        }
    }

    private fun setLoading(loading: Boolean) {
        binding.btnSignIn.isEnabled = !loading
        binding.progressLogin.visibility = if (loading) View.VISIBLE else View.GONE
        if (loading) {
            binding.tvLoginError.visibility = View.GONE
        }
    }

    private fun showError(msg: String) {
        binding.tvLoginError.text = msg
        binding.tvLoginError.visibility = View.VISIBLE
    }

    private fun goToSalesOrders() {
        startActivity(Intent(this, SalesOrdersActivity::class.java))
        finish()
    }

    override fun onDestroy() {
        super.onDestroy()
        uiScope.cancel()
    }
}
