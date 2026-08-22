import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'

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
  const ageRange = ref(saved?.ageRange ?? null)
  const dedupeStatus = ref(saved?.dedupeStatus ?? (saved?.uniqueOnly ? 'unique' : null))
  const importBatchId = ref(saved?.importBatchId ?? null)
  // Whether the collapsible advanced-filter panel is expanded.
  const panelOpen = ref(saved?.panelOpen ?? false)

  // Filters that live inside the collapsible panel. Surfaced as a count on the
  // toggle so active conditions are never hidden with no indication.
  const advancedCount = computed(() => {
    let n = 0
    if (educationLevel.value) n++
    if (experienceRange.value) n++
    if (scoreRange.value) n++
    if (aiTier.value != null && aiTier.value !== '') n++
    if (candidateType.value) n++
    if (ageRange.value) n++
    if (dedupeStatus.value) n++
    if (topUniversityOnly.value) n++
    if (hardFilterPassedOnly.value) n++
    n += selectedSkills.value.length
    return n
  })

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
        ageRange: ageRange.value,
        dedupeStatus: dedupeStatus.value,
        importBatchId: importBatchId.value,
        panelOpen: panelOpen.value,
      })
    )
  }

  watch([searchName, educationLevel, selectedSkills, experienceRange, scoreRange, topUniversityOnly, aiTier, hardFilterPassedOnly, bookmarkedOnly, candidateType, ageRange, dedupeStatus, importBatchId, panelOpen], persist, { deep: true })

  /** Reset only the filters inside the collapsible panel. */
  function clearAdvanced() {
    educationLevel.value = null
    selectedSkills.value = []
    experienceRange.value = null
    scoreRange.value = null
    topUniversityOnly.value = false
    aiTier.value = null
    hardFilterPassedOnly.value = false
    candidateType.value = null
    ageRange.value = null
    dedupeStatus.value = null
  }

  function clearAll() {
    clearAdvanced()
    searchName.value = ''
    bookmarkedOnly.value = false
    importBatchId.value = null
    // Keep panelOpen: whether the panel is expanded is a UI preference, not a
    // filter, so clearing conditions should not collapse it under the user.
    persist()
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
    ageRange,
    dedupeStatus,
    importBatchId,
    panelOpen,
    advancedCount,
    clearAdvanced,
    clearAll,
  }
})
