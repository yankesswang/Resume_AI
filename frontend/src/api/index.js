import axios from 'axios'

const api = axios.create({
  baseURL: '',
})

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
