import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { fetchInvitationSentIds, setInvitationSent } from '../api'

export const useInvitationStore = defineStore('invitations', () => {
  const set = ref(new Set())

  const allIds = computed(() => [...set.value])
  const count = computed(() => set.value.size)

  async function load() {
    const ids = await fetchInvitationSentIds()
    set.value = new Set(ids)
  }

  async function toggle(id) {
    const numId = Number(id)
    const nowSent = !set.value.has(numId)
    if (nowSent) {
      set.value.add(numId)
    } else {
      set.value.delete(numId)
    }
    set.value = new Set(set.value) // trigger reactivity
    await setInvitationSent(numId, nowSent)
  }

  function has(id) {
    return set.value.has(Number(id))
  }

  return { set, load, toggle, has, allIds, count }
})
