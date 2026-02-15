import { defineStore } from 'pinia'
import { ref } from 'vue'

const STORAGE_KEY = 'resume-ai-bookmarks'

export const useBookmarkStore = defineStore('bookmarks', () => {
  const set = ref(new Set(JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]')))

  function persist() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify([...set.value]))
  }

  function toggle(id) {
    if (set.value.has(id)) {
      set.value.delete(id)
    } else {
      set.value.add(id)
    }
    set.value = new Set(set.value) // trigger reactivity
    persist()
  }

  function has(id) {
    return set.value.has(id)
  }

  return { set, toggle, has }
})
