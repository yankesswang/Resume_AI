import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { authConfig, fetchMe, login as apiLogin, register as apiRegister } from '../api'

// The token is kept in localStorage rather than in memory alone, or a page
// refresh would log the user out — in an Electron shell that is every reload.
// This does mean a token is readable by any script running on the page, which
// is a real trade-off: an HttpOnly cookie would not be. It is acceptable here
// because the app serves no third-party content and the token expires in
// hours, and it is the piece to revisit first if that ever changes.
const TOKEN_KEY = 'resume_ai_token'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem(TOKEN_KEY) || '')
  const user = ref(null)
  const config = ref(null)
  const ready = ref(false)

  // Whether the backend requires credentials at all. With AUTH_ENABLED=false
  // the whole login flow is skipped, so local development is unchanged.
  const authRequired = computed(() => config.value?.auth_enabled !== false)
  const isAuthenticated = computed(() => !authRequired.value || !!user.value)
  const role = computed(() => user.value?.role || (authRequired.value ? '' : 'root'))
  const piiLevel = computed(() => user.value?.pii_level || 'full')
  const permissions = computed(() => user.value?.permissions || [])
  const isRoot = computed(() => role.value === 'root')

  function can(permission) {
    // With auth disabled nobody has a role, and gating the UI on an empty
    // permission list would hide every control in local development.
    if (!authRequired.value) return true
    return permissions.value.includes(permission)
  }

  function setToken(value) {
    token.value = value || ''
    if (value) localStorage.setItem(TOKEN_KEY, value)
    else localStorage.removeItem(TOKEN_KEY)
  }

  async function loadConfig() {
    try {
      config.value = await authConfig()
    } catch {
      // A backend too old to serve /api/auth/config, or unreachable. Assume
      // auth is on: guessing "off" would render the full UI to someone who
      // cannot actually load any of it.
      config.value = { auth_enabled: true, registration_open: false, root_configured: true }
    }
  }

  async function refresh() {
    if (!token.value) {
      user.value = null
      return null
    }
    try {
      const me = await fetchMe()
      user.value = me.kind === 'user' ? me : null
      return user.value
    } catch {
      // Expired, revoked, or the account was suspended. Drop it rather than
      // retrying every request with a credential the server rejects.
      setToken('')
      user.value = null
      return null
    }
  }

  async function init() {
    await loadConfig()
    if (authRequired.value) await refresh()
    ready.value = true
  }

  async function login(email, password) {
    const result = await apiLogin(email, password)
    setToken(result.access_token)
    user.value = result.user
    return result.user
  }

  async function register(payload) {
    return apiRegister(payload)
  }

  function logout() {
    setToken('')
    user.value = null
  }

  return {
    token, user, config, ready,
    authRequired, isAuthenticated, role, piiLevel, permissions, isRoot,
    can, init, login, register, logout, refresh, loadConfig,
  }
})
