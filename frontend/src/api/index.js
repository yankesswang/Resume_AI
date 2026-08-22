import axios from 'axios'

const api = axios.create({
  baseURL: '',
})

const TOKEN_KEY = 'resume_ai_token'

// Read from storage per request rather than captured once at module load: the
// token changes on login, logout and password change, and a captured copy
// would keep sending the old one until a reload.
api.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// A 401 means the session is gone — expired, revoked, or the account was
// suspended by root mid-session. Clear it and send the user to the login
// screen, rather than leaving the app half-working with a dead credential.
//
// 403 is deliberately NOT handled here: it means "logged in, not allowed",
// and redirecting to login would suggest re-authenticating fixes it. Views
// surface that message where the action was attempted.
let onUnauthorized = null
export function setUnauthorizedHandler(fn) {
  onUnauthorized = fn
}

api.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error?.response?.status
    const url = error?.config?.url || ''
    // The login endpoint's own 401 is "wrong password", not an expired
    // session, and must reach the form instead of triggering a redirect.
    if (status === 401 && !url.includes('/api/auth/login')) {
      localStorage.removeItem(TOKEN_KEY)
      if (onUnauthorized) onUnauthorized()
    }
    return Promise.reject(error)
  },
)

// --- Auth ---

export function authConfig() {
  return api.get('/api/auth/config').then((r) => r.data)
}

export function login(email, password) {
  return api.post('/api/auth/login', { email, password }).then((r) => r.data)
}

export function register(payload) {
  return api.post('/api/auth/register', payload).then((r) => r.data)
}

export function fetchMe() {
  return api.get('/api/auth/me').then((r) => r.data)
}

export function changePassword(currentPassword, newPassword) {
  return api
    .post('/api/auth/me/password', {
      current_password: currentPassword,
      new_password: newPassword,
    })
    .then((r) => r.data)
}

// --- Account administration (root only) ---

export function fetchUsers(status = null) {
  return api
    .get('/api/admin/users', { params: status ? { status } : {} })
    .then((r) => r.data)
}

export function fetchUser(id) {
  return api.get(`/api/admin/users/${id}`).then((r) => r.data)
}

export function approveUser(id, { role, piiLevel, note = '' }) {
  return api
    .post(`/api/admin/users/${id}/approve`, { role, pii_level: piiLevel, note })
    .then((r) => r.data)
}

export function rejectUser(id, note = '') {
  return api.post(`/api/admin/users/${id}/reject`, { note }).then((r) => r.data)
}

export function updateUserGrade(id, { role = null, piiLevel = null, note = '' }) {
  return api
    .put(`/api/admin/users/${id}/grade`, { role, pii_level: piiLevel, note })
    .then((r) => r.data)
}

export function updateUserStatus(id, status, note = '') {
  return api.put(`/api/admin/users/${id}/status`, { status, note }).then((r) => r.data)
}

export function fetchUserAudit(limit = 100) {
  return api.get('/api/admin/user-audit', { params: { limit } }).then((r) => r.data)
}

function buildParams(options = {}) {
  const params = {}
  if (options.scope) params.scope = options.scope
  if (options.batchId) params.batch_id = options.batchId
  return params
}

export function fetchCandidates(options = {}) {
  return api.get('/api/candidates', { params: buildParams(options) }).then((r) => r.data)
}

export function fetchCandidate(id) {
  return api.get(`/api/candidates/${id}`).then((r) => r.data)
}

export function fetchMatchResult(id) {
  return api.get(`/api/candidates/${id}/match`).then((r) => r.data)
}

export function triggerMatch(id) {
  return api.post(`/api/candidates/${id}/match`).then((r) => r.data)
}

export function fetchScorecard(id) {
  return api.get(`/api/candidates/${id}/scorecard`).then((r) => r.data)
}

export function batchMatch() {
  return api.post('/api/candidates/batch-match').then((r) => r.data)
}

export function fetchFilters(options = {}) {
  return api.get('/api/filters', { params: buildParams(options) }).then((r) => r.data)
}

export function fetchImportBatches() {
  return api.get('/api/import-batches').then((r) => r.data)
}

export function fetchImportBatch(id) {
  return api.get(`/api/import-batches/${id}`).then((r) => r.data)
}

export function deleteImportBatch(id, deleteCandidates = false) {
  // axios sends a DELETE body only via the `data` key.
  return api
    .delete(`/api/import-batches/${id}`, { data: { delete_candidates: deleteCandidates } })
    .then((r) => r.data)
}

export function fetchImportFileCandidates(fileId) {
  return api.get(`/api/import-files/${fileId}/candidates`).then((r) => r.data)
}

export function uploadPdf(file) {
  const form = new FormData()
  form.append('file', file)
  return api.post('/api/upload', form).then((r) => r.data)
}

export function createManualCandidate(data) {
  return api.post('/api/candidates/manual', data).then((r) => r.data)
}

export function deleteCandidate(id) {
  return api.delete(`/api/candidates/${id}`).then((r) => r.data)
}

export function fetchInterestedIds() {
  return api.get('/api/interested').then((r) => r.data.ids)
}

export function setInterested(id, interested) {
  return api.post(`/api/candidates/${id}/interested`, { interested }).then((r) => r.data)
}

export function fetchInvitationSentIds() {
  return api.get('/api/invitation-sent').then((r) => r.data.ids)
}

export function setInvitationSent(id, sent) {
  return api.post(`/api/candidates/${id}/invitation-sent`, { invitation_sent: sent }).then((r) => r.data)
}

export function generateInterviewQuestions(id) {
  return api.post(`/api/candidates/${id}/interview-questions`).then((r) => r.data)
}

export function batchInterviewQuestions() {
  return api.post('/api/batch-interview-questions').then((r) => r.data)
}

export function fetchInterviews() {
  return api.get('/api/interviews').then((r) => r.data)
}

export function createInterview(data) {
  return api.post('/api/interviews', data).then((r) => r.data)
}

export function updateInterview(id, data) {
  return api.put(`/api/interviews/${id}`, data).then((r) => r.data)
}

export function deleteInterview(id) {
  return api.delete(`/api/interviews/${id}`).then((r) => r.data)
}

export function fetchInterviewStatuses() {
  return api.get('/api/interview-statuses').then((r) => r.data)
}

export function createInterviewStatus(label, color = 'gray') {
  return api.post('/api/interview-statuses', { label, color }).then((r) => r.data)
}

export function deleteInterviewStatus(id) {
  return api.delete(`/api/interview-statuses/${id}`).then((r) => r.data)
}

export function fetchInterviewTypes() {
  return api.get('/api/interview-types').then((r) => r.data)
}

export function createInterviewType(label, color = 'gray') {
  return api.post('/api/interview-types', { label, color }).then((r) => r.data)
}

export function deleteInterviewType(id) {
  return api.delete(`/api/interview-types/${id}`).then((r) => r.data)
}

export function exportCandidates(ids) {
  return api.post('/api/export/candidates', { candidate_ids: ids }).then((r) => r.data)
}

export function exportCandidatesCsv(ids) {
  return api.post('/api/export/candidates/csv', { candidate_ids: ids }, { responseType: 'blob' }).then((r) => {
    const url = window.URL.createObjectURL(r.data)
    const a = document.createElement('a')
    a.href = url
    a.download = 'interested_candidates.csv'
    a.click()
    window.URL.revokeObjectURL(url)
  })
}

export default api

// --- Email templates ---

export function fetchEmailTemplates() {
  return api.get('/api/email-templates').then((r) => r.data)
}

export function saveEmailTemplates(templates, sender) {
  return api.put('/api/email-templates', { templates, sender }).then((r) => r.data)
}

export function resetEmailTemplates() {
  return api.post('/api/email-templates/reset').then((r) => r.data)
}

export function composeEmail(candidateId, templateId, interviewId = null) {
  return api
    .post(`/api/candidates/${candidateId}/compose-email`, {
      template_id: templateId,
      interview_id: interviewId,
    })
    .then((r) => r.data)
}

// --- Scoring configuration ---
export function fetchScoringConfig() {
  return api.get('/api/scoring-config').then((r) => r.data)
}
export function saveScoringConfig(config) {
  return api.put('/api/scoring-config', { config }).then((r) => r.data)
}
export function validateScoringConfig(config) {
  return api.post('/api/scoring-config/validate', { config }).then((r) => r.data)
}
export function resetScoringConfig() {
  return api.post('/api/scoring-config/reset').then((r) => r.data)
}
export function fetchSchoolRoster() {
  return api.get('/api/scoring-config/school-roster').then((r) => r.data)
}
export function fetchMajorCatalogue() {
  return api.get('/api/scoring-config/major-catalogue').then((r) => r.data)
}
export function previewScoringConfig(config) {
  return api.post('/api/scoring-config/preview', { config }).then((r) => r.data)
}

// --- Job postings & domain scoring profiles ---

export function fetchJobPostings() {
  return api.get('/api/job-postings').then((r) => r.data)
}

export function fetchJobPosting(id) {
  return api.get(`/api/job-postings/${id}`).then((r) => r.data)
}

// Accepts either a File or pasted text. Generation runs two LLM calls over the
// whole document, so this can take a minute — the default axios timeout of 0
// (no timeout) is what we want here.
export function uploadJobPosting({ file, text, title }) {
  const form = new FormData()
  if (file) form.append('file', file)
  if (text) form.append('text', text)
  if (title) form.append('title', title)
  return api
    .post('/api/job-postings/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    .then((r) => r.data)
}

export function saveJobProfile(id, profile, activate = false) {
  return api
    .put(`/api/job-postings/${id}/profile`, { profile, activate })
    .then((r) => r.data)
}

export function regenerateJobProfile(id) {
  return api.post(`/api/job-postings/${id}/profile/regenerate`).then((r) => r.data)
}

export function previewJobProfile(id, { profile = null, limit = 30 } = {}) {
  return api
    .post(`/api/job-postings/${id}/preview`, { profile, limit })
    .then((r) => r.data)
}

export function activateJobPosting(id) {
  return api.post(`/api/job-postings/${id}/activate`).then((r) => r.data)
}

export function deleteJobPosting(id) {
  return api.delete(`/api/job-postings/${id}`).then((r) => r.data)
}

export function fetchProfileTemplate(id) {
  return api.get(`/api/job-postings/${id}/profile/template`).then((r) => r.data)
}

// --- LLM provider settings -------------------------------------------------
// The API key is never returned in clear text; a masked value echoed back on
// save means "keep the stored key", so the form can be submitted untouched.

export function fetchLLMConfig() {
  return api.get('/api/llm-config').then((r) => r.data)
}

export function saveLLMConfig(config) {
  return api.put('/api/llm-config', { config }).then((r) => r.data)
}

export function validateLLMConfig(config) {
  return api.post('/api/llm-config/validate', { config }).then((r) => r.data)
}

export function resetLLMConfig() {
  return api.post('/api/llm-config/reset').then((r) => r.data)
}

// Tests the config currently in the form, saved or not, so a key can be
// verified before it is committed.
export function testLLMConfig(config, section = 'chat') {
  return api.post('/api/llm-config/test', { config, section }).then((r) => r.data)
}
