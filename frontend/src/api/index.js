import axios from 'axios'

const api = axios.create({
  baseURL: '',
})

export function fetchCandidates() {
  return api.get('/api/candidates').then((r) => r.data)
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

export function fetchFilters() {
  return api.get('/api/filters').then((r) => r.data)
}

export function uploadPdf(file) {
  const form = new FormData()
  form.append('file', file)
  return api.post('/api/upload', form).then((r) => r.data)
}

export default api
