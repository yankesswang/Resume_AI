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
  fetchInterviewTypes,
  createInterviewType,
  deleteInterviewType,
} from '../api'

export const useInterviewStore = defineStore('interviews', () => {
  const interviews = ref([])
  const statuses = ref([])
  // Interview types are operator vocabulary like statuses, not a fixed enum —
  // loaded from the API so adding one does not need a frontend rebuild.
  const types = ref([])

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
    const [ivList, statusList, typeList] = await Promise.all([
      fetchInterviews(),
      fetchInterviewStatuses(),
      fetchInterviewTypes(),
    ])
    interviews.value = ivList
    statuses.value = statusList
    types.value = typeList
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

  async function addType(label, color) {
    const result = await createInterviewType(label, color)
    types.value = [...types.value, { ...result, sort_order: 999 }]
    return result
  }

  async function removeType(id) {
    await deleteInterviewType(id)
    types.value = types.value.filter((t) => t.id !== id)
  }

  return {
    interviews,
    statuses,
    types,
    latestByCandidate,
    load,
    saveInterview,
    removeInterview,
    addStatus,
    removeStatus,
    addType,
    removeType,
  }
})
