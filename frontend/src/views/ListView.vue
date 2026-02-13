<template>
  <v-layout>
    <v-app-bar flat density="comfortable" class="app-header">
      <v-app-bar-title class="text-h6 font-weight-bold text-white">
        <v-icon class="mr-1" size="small">mdi-file-document-outline</v-icon>
        Resume AI
      </v-app-bar-title>
      <v-spacer />
      <v-chip
        v-if="candidates.length"
        variant="tonal"
        color="white"
        size="small"
        class="mr-3"
      >
        {{ candidates.length }} candidates
      </v-chip>
      <v-btn variant="tonal" color="white" class="mr-2" @click="showUpload = true">
        <v-icon start>mdi-upload</v-icon> Upload
      </v-btn>
    </v-app-bar>

    <v-main>
      <v-container fluid class="pa-6">
        <FilterPanel
          :education-levels="filterOptions.education_levels"
          :skill-tags="filterOptions.skill_tags"
          :experience-ranges="filterOptions.experience_ranges"
          :score-ranges="filterOptions.score_ranges"
        />
        <CandidateTable :candidates="candidates" />
      </v-container>
    </v-main>

    <!-- Upload dialog -->
    <v-dialog v-model="showUpload" max-width="520">
      <v-card rounded="lg">
        <v-card-title class="text-h6 font-weight-bold">Upload Resume PDF</v-card-title>
        <v-card-text>
          <v-file-input
            v-model="uploadFile"
            label="Select PDF"
            accept=".pdf"
            prepend-icon="mdi-file-pdf-box"
            show-size
          />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn @click="showUpload = false">Cancel</v-btn>
          <v-btn color="primary" :loading="uploading" :disabled="!uploadFile" @click="doUpload">
            Upload
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-layout>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { fetchCandidates, fetchFilters, uploadPdf } from '../api'
import FilterPanel from '../components/FilterPanel.vue'
import CandidateTable from '../components/CandidateTable.vue'

const router = useRouter()
const candidates = ref([])
const filterOptions = ref({ education_levels: [], skill_tags: [], experience_ranges: [], score_ranges: [] })
const showUpload = ref(false)
const uploadFile = ref(null)
const uploading = ref(false)

async function loadData() {
  const [cands, filters] = await Promise.all([fetchCandidates(), fetchFilters()])
  candidates.value = cands
  filterOptions.value = filters
}

async function doUpload() {
  if (!uploadFile.value) return
  uploading.value = true
  try {
    await uploadPdf(uploadFile.value)
    showUpload.value = false
    uploadFile.value = null
    await loadData()
  } catch (err) {
    console.error('Upload failed:', err)
  } finally {
    uploading.value = false
  }
}

onMounted(loadData)
</script>

<style scoped>
.app-header {
  background: linear-gradient(135deg, #1A237E 0%, #303F9F 50%, #00897B 100%) !important;
}
</style>
