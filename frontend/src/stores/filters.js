import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

const STORAGE_KEY = 'resume-ai-filters'

function loadFromStorage() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

export const useFilterStore = defineStore('filters', () => {
  const saved = loadFromStorage()

  const searchName = ref(saved?.searchName ?? '')
  const educationLevel = ref(saved?.educationLevel ?? null)
  const selectedSkills = ref(saved?.selectedSkills ?? [])
  const experienceRange = ref(saved?.experienceRange ?? null)
  const scoreRange = ref(saved?.scoreRange ?? null)
  const topUniversityOnly = ref(saved?.topUniversityOnly ?? false)
  const aiTier = ref(saved?.aiTier ?? null)
  const hardFilterPassedOnly = ref(saved?.hardFilterPassedOnly ?? false)
  const bookmarkedOnly = ref(saved?.bookmarkedOnly ?? false)
  const candidateType = ref(saved?.candidateType ?? null)
  const dedupeStatus = ref(saved?.dedupeStatus ?? (saved?.uniqueOnly ? 'unique' : null))
  const importBatchId = ref(saved?.importBatchId ?? null)

  function persist() {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        searchName: searchName.value,
        educationLevel: educationLevel.value,
        selectedSkills: selectedSkills.value,
        experienceRange: experienceRange.value,
        scoreRange: scoreRange.value,
        topUniversityOnly: topUniversityOnly.value,
        aiTier: aiTier.value,
        hardFilterPassedOnly: hardFilterPassedOnly.value,
        bookmarkedOnly: bookmarkedOnly.value,
        candidateType: candidateType.value,
        dedupeStatus: dedupeStatus.value,
        importBatchId: importBatchId.value,
      })
    )
  }

  watch([searchName, educationLevel, selectedSkills, experienceRange, scoreRange, topUniversityOnly, aiTier, hardFilterPassedOnly, bookmarkedOnly, candidateType, dedupeStatus, importBatchId], persist, { deep: true })

  function clearAll() {
    searchName.value = ''
    educationLevel.value = null
    selectedSkills.value = []
    experienceRange.value = null
    scoreRange.value = null
    topUniversityOnly.value = false
    aiTier.value = null
    hardFilterPassedOnly.value = false
    bookmarkedOnly.value = false
    candidateType.value = null
    dedupeStatus.value = null
    importBatchId.value = null
    localStorage.removeItem(STORAGE_KEY)
  }

  return {
    searchName,
    educationLevel,
    selectedSkills,
    experienceRange,
    scoreRange,
    topUniversityOnly,
    aiTier,
    hardFilterPassedOnly,
    bookmarkedOnly,
    candidateType,
    dedupeStatus,
    importBatchId,
    clearAll,
  }
})
