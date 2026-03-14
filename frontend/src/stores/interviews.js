import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import {
  fetchInterviews,
  createInterview,
  updateInterview,
  deleteInterview,
  fetchInterviewStatuses,
  createInterviewStatus,
  deleteInterviewStatus,
} from '../api'

export const useInterviewStore = defineStore('interviews', () => {
  const interviews = ref([])
  const statuses = ref([])

  // candidateId → latest interview (by interview_date DESC)
  const latestByCandidate = computed(() => {
    const map = {}
    for (const iv of interviews.value) {
      if (!iv.candidate_id) continue
      const cid = iv.candidate_id
      if (!map[cid] || iv.interview_date > map[cid].interview_date) {
        map[cid] = iv
      }
    }
    return map
  })

  async function load() {
    const [ivList, statusList] = await Promise.all([
      fetchInterviews(),
      fetchInterviewStatuses(),
    ])
    interviews.value = ivList
    statuses.value = statusList
  }

  // id=null → create, id=number → update; reloads interviews after
  async function saveInterview(payload, id = null) {
    if (id) {
      await updateInterview(id, payload)
    } else {
      await createInterview(payload)
    }
    interviews.value = await fetchInterviews()
  }

  async function removeInterview(id) {
    await deleteInterview(id)
    interviews.value = interviews.value.filter((iv) => iv.id !== id)
  }

  async function addStatus(label, color) {
    const result = await createInterviewStatus(label, color)
    statuses.value = [
      ...statuses.value,
      { id: result.id, label: result.label, color: result.color, sort_order: 999 },
    ]
    return result
  }

  async function removeStatus(id) {
    await deleteInterviewStatus(id)
    statuses.value = statuses.value.filter((s) => s.id !== id)
  }

  return {
    interviews,
    statuses,
    latestByCandidate,
    load,
    saveInterview,
    removeInterview,
    addStatus,
    removeStatus,
  }
})
