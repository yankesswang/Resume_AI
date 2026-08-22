<template>
  <div class="flex flex-col h-full overflow-hidden">
    <!-- Toolbar -->
    <div class="flex items-center justify-between px-5 py-3 bg-surface border-b border-line shrink-0">
      <div class="flex items-center gap-2 text-small text-ink-muted min-w-0">
        <span class="font-semibold text-ink whitespace-nowrap">評分設定</span>
        <span class="text-ink-faint">/</span>
        <span :class="customized ? 'text-warn-ink font-semibold' : 'text-ink-muted'">
          {{ customized ? '已自訂' : '使用預設值' }}
        </span>
        <span v-if="dirty" class="text-ink-faint">·</span>
        <span v-if="dirty" class="text-brand-ink font-semibold">尚未儲存</span>
      </div>
      <div class="flex items-center gap-2">
        <button
          @click="runPreview"
          :disabled="previewing || !!errors.length"
          class="inline-flex items-center gap-1.5 px-3 py-1.5 text-micro font-semibold border border-line rounded-control text-ink-muted hover:border-line-strong hover:text-ink disabled:opacity-50 transition"
        >
          {{ previewing ? '試算中…' : '試算影響' }}
        </button>
        <button
          @click="doReset"
          :disabled="saving"
          class="px-3 py-1.5 text-micro font-semibold border border-line rounded-control text-ink-muted hover:border-line-strong disabled:opacity-50 transition"
        >
          還原預設
        </button>
        <button
          @click="doSave"
          :disabled="saving || !!errors.length || !dirty"
          class="px-4 py-1.5 text-micro font-semibold bg-brand text-white rounded-control hover:bg-brand-hover disabled:opacity-40 transition"
        >
          {{ saving ? '儲存中…' : '儲存' }}
        </button>
      </div>
    </div>

    <div class="flex-1 overflow-auto p-5">
      <div v-if="loading" class="py-20 text-center text-small text-ink-faint">載入中…</div>

      <div v-else-if="loadError" class="py-20 text-center">
        <h3 class="text-small font-semibold text-ink mb-3">無法連線到後端</h3>
        <button @click="load" class="px-4 py-2 text-small font-semibold bg-brand text-white rounded-control">重試</button>
      </div>

      <div v-else class="max-w-5xl mx-auto space-y-5">
        <!-- Validation errors -->
        <div v-if="errors.length" class="rounded-card border border-bad-line bg-bad-soft p-4">
          <p class="text-small font-semibold text-bad-ink mb-1.5">設定有誤，無法儲存</p>
          <ul class="text-micro text-bad-ink space-y-1 list-disc list-inside">
            <li v-for="(e, i) in errors" :key="i">{{ e }}</li>
          </ul>
        </div>
        <div v-if="savedMsg" class="rounded-card border border-good-line bg-good-soft p-3 text-small text-good-ink">
          {{ savedMsg }}
        </div>

        <!-- Weights -->
        <section class="bg-surface rounded-card border border-line p-5">
          <header class="mb-1">
            <h2 class="text-small font-semibold text-ink">評分權重</h2>
            <p class="text-micro text-ink-muted mt-0.5">
              總分 = 各構面分數 × 權重，總和必須為 100%。
            </p>
          </header>
          <div class="mt-4 space-y-3">
            <div v-for="k in weightKeys" :key="k" class="flex items-center gap-3">
              <span class="w-24 text-micro font-medium text-ink-muted shrink-0">{{ weightLabels[k] }}</span>
              <input
                type="range" min="0" max="1" step="0.01"
                v-model.number="cfg.weights[k]"
                class="flex-1 accent-brand"
              />
              <input
                type="number" min="0" max="1" step="0.01"
                v-model.number="cfg.weights[k]"
                class="w-20 field px-2 py-1 text-micro text-right"
              />
              <span class="w-12 text-micro text-ink-muted text-right">{{ Math.round(cfg.weights[k] * 100) }}%</span>
            </div>
          </div>
          <div
            class="mt-4 flex items-center justify-between px-3 py-2 rounded-control text-micro font-semibold"
            :class="weightOk ? 'bg-surface-2 text-ink-muted' : 'bg-bad-soft text-bad-ink'"
          >
            <span>總和</span>
            <span>{{ Math.round(weightTotal * 100) }}%<template v-if="!weightOk"> — 必須為 100%</template></span>
          </div>
          <button
            v-if="!weightOk"
            @click="normalizeWeights"
            class="mt-2 text-micro font-semibold text-brand-ink hover:text-brand-ink"
          >
            自動調整為 100%
          </button>
        </section>

        <!-- Tier bands -->
        <section class="bg-surface rounded-card border border-line p-5">
          <header class="mb-3">
            <h2 class="text-small font-semibold text-ink">AI 層級分數帶</h2>
            <p class="text-micro text-ink-muted mt-0.5">
              每個層級的起始分與加分上限。區間不可重疊，否則低層級候選人會贏過高層級。
            </p>
          </header>
          <div class="space-y-2.5">
            <div v-for="t in tierKeys" :key="t" class="flex items-center gap-3">
              <span class="w-28 text-micro font-medium text-ink-muted shrink-0">
                T{{ t }} · {{ cfg.tiers[t].label }}
              </span>
              <label class="text-micro text-ink-faint">起始</label>
              <input type="number" min="0" max="100" v-model.number="cfg.tiers[t].base"
                class="w-16 field px-2 py-1 text-micro text-right" />
              <label class="text-micro text-ink-faint">加分上限</label>
              <input type="number" min="0" max="50" v-model.number="cfg.tiers[t].bonus_cap"
                class="w-16 field px-2 py-1 text-micro text-right" />
              <div class="flex-1 h-2 bg-surface-2 rounded-full relative overflow-hidden">
                <div
                  class="absolute h-full rounded-full"
                  :class="tierColors[t]"
                  :style="{ left: cfg.tiers[t].base + '%', width: Math.min(cfg.tiers[t].bonus_cap, 100 - cfg.tiers[t].base) + '%' }"
                />
              </div>
              <span class="w-20 text-micro text-ink-muted text-right tabular-nums">
                {{ cfg.tiers[t].base }}–{{ Math.min(cfg.tiers[t].base + cfg.tiers[t].bonus_cap, 100) }}
              </span>
            </div>
          </div>
        </section>

        <!-- Keyword floor + semantic -->
        <div class="grid grid-cols-1 md:grid-cols-2 gap-5">
          <section class="bg-surface rounded-card border border-line p-5">
            <h2 class="text-small font-semibold text-ink">關鍵字保底</h2>
            <p class="text-micro text-ink-muted mt-0.5 mb-3">
              當 LLM 判定偏低時，用履歷中的高辨識度技術詞往上修正（只會提高，不會降低）。
            </p>
            <label class="flex items-center gap-2 text-micro text-ink-muted mb-3">
              <input type="checkbox" v-model="cfg.keyword_floor.enabled" class="accent-brand" />
              啟用關鍵字保底
            </label>
            <div class="flex items-center gap-3">
              <span class="text-micro text-ink-muted">最少須命中</span>
              <input type="number" min="1" max="6" v-model.number="cfg.keyword_floor.min_signals"
                class="w-16 field px-2 py-1 text-micro text-right" />
              <span class="text-micro text-ink-faint">個不同訊號</span>
            </div>
            <p class="text-micro text-ink-faint mt-2">
              設為 1 過於寬鬆：71% 履歷會提到 PyTorch／Training，多半只是修過課。
            </p>
          </section>

          <section class="bg-surface rounded-card border border-line p-5">
            <h2 class="text-small font-semibold text-ink">語意相似度校正</h2>
            <p class="text-micro text-ink-muted mt-0.5 mb-3">
              原始 cosine 值集中在狹窄區間，需拉伸後才有鑑別度。
            </p>
            <div class="space-y-2">
              <div class="flex items-center gap-3">
                <span class="w-20 text-micro text-ink-muted">下界</span>
                <input type="number" min="0" max="1" step="0.01" v-model.number="cfg.semantic.rescale_low"
                  class="w-20 field px-2 py-1 text-micro text-right" />
                <span class="text-micro text-ink-faint">以下視為 0 分</span>
              </div>
              <div class="flex items-center gap-3">
                <span class="w-20 text-micro text-ink-muted">上界</span>
                <input type="number" min="0" max="1" step="0.01" v-model.number="cfg.semantic.rescale_high"
                  class="w-20 field px-2 py-1 text-micro text-right" />
                <span class="text-micro text-ink-faint">以上視為滿分</span>
              </div>
            </div>
            <div class="mt-3 pt-3 border-t border-line">
              <span class="text-micro text-ink-muted">技能標籤權重係數</span>
              <div class="flex items-center gap-3 mt-1.5">
                <input type="range" min="0" max="1" step="0.05" v-model.number="cfg.tag_weight_factor"
                  class="flex-1 accent-brand" />
                <span class="w-12 text-micro text-ink-muted text-right">{{ cfg.tag_weight_factor }}</span>
              </div>
              <p class="text-micro text-ink-faint mt-1">
                只寫在技能欄、工作經歷沒佐證的關鍵字，以此比例折算。
              </p>
            </div>
          </section>
        </div>

        <!-- Education & skills -->
        <div class="grid grid-cols-1 md:grid-cols-2 gap-5">
          <section class="bg-surface rounded-card border border-line p-5">
            <h2 class="text-small font-semibold text-ink">學歷分數</h2>
            <p class="text-micro text-ink-muted mt-0.5 mb-3">學校等級與科系相關性的配分。</p>
            <div class="grid grid-cols-5 gap-2">
              <div v-for="(_, k) in cfg.education.school_points" :key="k">
                <label class="block text-micro text-ink-muted mb-1">{{ k }} 級</label>
                <input type="number" step="0.5" v-model.number="cfg.education.school_points[k]"
                  class="w-full field px-2 py-1 text-micro text-right" />
              </div>
            </div>
            <div class="grid grid-cols-3 gap-2 mt-3">
              <div v-for="(_, k) in cfg.education.major_points" :key="k">
                <label class="block text-micro text-ink-muted mb-1">科系 {{ k }}</label>
                <input type="number" step="0.5" v-model.number="cfg.education.major_points[k]"
                  class="w-full field px-2 py-1 text-micro text-right" />
              </div>
            </div>

          </section>

          <section class="bg-surface rounded-card border border-line p-5">
            <h2 class="text-small font-semibold text-ink">技能生態與扣分</h2>
            <p class="text-micro text-ink-muted mt-0.5 mb-3">技術棧基準分，以及聲稱無佐證時的扣分。</p>
            <div class="grid grid-cols-2 gap-2">
              <div v-for="(_, k) in cfg.skills.ecosystem_scores" :key="k">
                <label class="block text-micro text-ink-muted mb-1">{{ k }}</label>
                <input type="number" v-model.number="cfg.skills.ecosystem_scores[k]"
                  class="w-full field px-2 py-1 text-micro text-right" />
              </div>
            </div>
            <div class="grid grid-cols-3 gap-2 mt-3">
              <div>
                <label class="block text-micro text-ink-muted mb-1">查無佐證</label>
                <input type="number" step="0.5" v-model.number="cfg.skills.penalty_unsupported"
                  class="w-full field px-2 py-1 text-micro text-right" />
              </div>
              <div>
                <label class="block text-micro text-ink-muted mb-1">僅作品集</label>
                <input type="number" step="0.5" v-model.number="cfg.skills.penalty_portfolio_only"
                  class="w-full field px-2 py-1 text-micro text-right" />
              </div>
              <div>
                <label class="block text-micro text-ink-muted mb-1">關鍵字灌水</label>
                <input type="number" step="0.5" v-model.number="cfg.skills.penalty_keyword_stuffing"
                  class="w-full field px-2 py-1 text-micro text-right" />
              </div>
            </div>
          </section>
        </div>

        <!-- School tiers: full width, because the groups need room to drag into. -->
        <section class="bg-surface rounded-card border border-line p-5">
          <div class="flex items-start justify-between gap-3 flex-wrap">
            <div>
              <h2 class="text-small font-semibold text-ink">學校分級</h2>
              <p class="text-micro text-ink-muted mt-0.5">
                拖曳學校到其他等級即可調整，或直接新增學校。只有被移動過的學校會存成覆蓋設定，其餘沿用內建分級。
              </p>
            </div>
            <div class="flex items-center gap-2">
              <span v-if="movedCount" class="text-micro text-ink-muted">已調整 {{ movedCount }} 間</span>
              <button v-if="movedCount" @click="resetSchoolTiers"
                class="rounded-control border border-line px-2.5 py-1 text-micro font-semibold text-ink-muted hover:border-line-strong">
                全部還原
              </button>
            </div>
          </div>

          <p v-if="rosterError" class="text-micro text-bad-ink mt-3">
            無法載入學校清單（{{ rosterError }}）。分級設定仍可使用，但需要手動輸入校名。
          </p>

          <div class="mt-4 grid grid-cols-1 gap-3 lg:grid-cols-4">
            <div v-for="tier in schoolTierKeys" :key="tier"
              class="rounded-control border p-3 transition-colors"
              :class="dragOverTier === tier ? toneFor(tier).drop : toneFor(tier).column"
              @dragover.prevent="dragOverTier = tier"
              @dragleave="dragOverTier === tier && (dragOverTier = null)"
              @drop.prevent="dropOnTier(tier)"
            >
              <div class="flex items-baseline justify-between gap-2">
                <h3 class="text-micro font-semibold" :class="toneFor(tier).header">{{ tier }} 級</h3>
                <span class="text-micro text-ink-faint">
                  {{ cfg.education.school_points[tier] }} 分 · {{ (schoolGroups[tier] || []).length }} 間
                </span>
              </div>
              <p class="text-micro text-ink-faint mt-0.5">{{ tierDescriptions[tier] }}</p>

              <div class="mt-2 space-y-1 max-h-72 overflow-auto" :ref="(el) => (listEls[tier] = el)">
                <div v-for="name in schoolGroups[tier] || []" :key="name"
                  draggable="true"
                  @dragstart="dragging = { name, from: tier }"
                  @dragend="dragging = null; dragOverTier = null"
                  class="group flex items-center gap-1 rounded-control border px-2 py-1 text-micro cursor-grab active:cursor-grabbing transition-shadow duration-500"
                  :class="[
                    toneFor(tier).chip,
                    isMoved(name) ? 'ring-1 ring-brand' : '',
                    justLanded === name ? 'ring-2 ring-brand' : '',
                  ]"
                >
                  <span class="flex-1 truncate" :title="name">{{ name }}</span>
                  <span v-if="isMoved(name)" class="text-ink-faint" title="已調整">•</span>
                  <button @click="removeSchool(tier, name)"
                    class="opacity-0 group-hover:opacity-100 text-ink-faint hover:text-bad-ink"
                    title="移除">×</button>
                </div>
                <p v-if="!(schoolGroups[tier] || []).length" class="text-micro text-ink-faint py-2">
                  拖曳學校到這裡
                </p>
              </div>

              <form @submit.prevent="addSchool(tier)" class="mt-2 flex gap-1">
                <input v-model="newSchool[tier]" placeholder="新增學校"
                  class="min-w-0 flex-1 field px-2 py-1 text-micro" />
                <button type="submit" class="rounded-control border border-line px-2 py-1 text-micro text-ink-muted hover:border-line-strong">
                  +
                </button>
              </form>
            </div>
          </div>

          <p class="text-micro text-ink-faint mt-3">
            未列出的學校仍會依內建規則自動分級（例如其他國立大學歸 C 級、未識別的學校歸 D 級）。
          </p>
        </section>

        <!-- Preview -->
        <section v-if="preview" class="bg-surface rounded-card border border-line p-5">
          <header class="mb-3">
            <h2 class="text-small font-semibold text-ink">試算結果</h2>
            <p class="text-micro text-ink-muted mt-0.5">
              取前 {{ preview.sample_size }} 位候選人重新計算（使用既有 LLM 快取，不會重新呼叫模型）。
              其中 <span class="font-semibold text-ink">{{ preview.changed }}</span> 位分數改變，
              平均變動 <span class="font-semibold" :class="preview.avg_delta >= 0 ? 'text-good-ink' : 'text-bad-ink'">
                {{ preview.avg_delta > 0 ? '+' : '' }}{{ preview.avg_delta }}</span> 分。
            </p>
          </header>
          <div class="overflow-x-auto">
            <table class="w-full text-micro">
              <thead class="text-ink-faint border-b border-line">
                <tr>
                  <th class="text-left font-medium py-1.5">候選人</th>
                  <th class="text-center font-medium">層級</th>
                  <th class="text-right font-medium">目前</th>
                  <th class="text-right font-medium">調整後</th>
                  <th class="text-right font-medium pr-1">變動</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="r in preview.results" :key="r.id" class="border-b border-line">
                  <td class="py-1.5 text-ink">{{ r.name || `#${r.id}` }}</td>
                  <td class="text-center text-ink-muted">T{{ r.tier }}</td>
                  <td class="text-right tabular-nums text-ink-muted">{{ r.before }}</td>
                  <td class="text-right tabular-nums font-semibold text-ink">{{ r.after }}</td>
                  <td
                    class="text-right tabular-nums pr-1 font-semibold"
                    :class="r.delta > 0 ? 'text-good-ink' : r.delta < 0 ? 'text-bad-ink' : 'text-ink-faint'"
                  >
                    {{ r.delta > 0 ? '+' : '' }}{{ r.delta }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <p class="text-micro text-ink-faint pb-4">
          儲存後需重新執行評分才會套用到既有候選人。演算法說明見 docs/SCORING_ALGORITHM.md。
        </p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import {
  fetchScoringConfig,
  fetchSchoolRoster,
  previewScoringConfig,
  resetScoringConfig,
  saveScoringConfig,
  validateScoringConfig,
} from '../api'

const cfg = ref(null)
const defaults = ref(null)
const customized = ref(false)
const loading = ref(true)
const loadError = ref(false)
const saving = ref(false)
const previewing = ref(false)
const errors = ref([])
const preview = ref(null)
const savedMsg = ref('')
const savedSnapshot = ref('')

const weightLabels = {
  experience: 'AI 經驗深度',
  engineering: '工程落地',
  semantic: '語意匹配',
  education: '教育背景',
  skills: '技能驗證',
}
const weightKeys = computed(() => Object.keys(weightLabels).filter((k) => cfg.value?.weights?.[k] != null))
const tierKeys = computed(() => Object.keys(cfg.value?.tiers ?? {}).sort((a, b) => Number(a) - Number(b)))
const tierColors = {
  0: 'bg-red-300',
  1: 'bg-ink-faint',
  2: 'bg-blue-400',
  3: 'bg-purple-400',
}

// --- School tiers ---------------------------------------------------------
// The groups shown are the built-in roster with the saved overrides applied on
// top. Only schools whose tier differs from the built-in one are written back,
// so the config stays a short list of decisions rather than a copy of the whole
// roster that would silently freeze future updates to the built-in tables.

// "S" is excluded: the scorer assigns it for a doctorate, not for a school.
const schoolTierKeys = computed(() =>
  Object.keys(cfg.value?.education?.school_points ?? {}).filter((k) => k !== 'S')
)

const tierDescriptions = {
  A: '頂尖大學',
  B: '中字輩、科大龍頭',
  C: '一般國立、知名私立',
  D: '其他',
}

// Colour climbs neutral → info → expert with rank, matching TierBadge, so the
// two pages read as one scale. D is neutral rather than red: "not a ranked
// school" is the common case, not an error.
const tierTones = {
  A: {
    header: 'text-expert-ink',
    chip: 'border-expert-line bg-expert-soft text-expert-ink',
    column: 'border-expert-line',
    drop: 'border-expert-ink bg-expert-soft',
  },
  B: {
    header: 'text-info-ink',
    chip: 'border-info-line bg-info-soft text-info-ink',
    column: 'border-info-line',
    drop: 'border-info-ink bg-info-soft',
  },
  C: {
    header: 'text-good-ink',
    chip: 'border-good-line bg-good-soft text-good-ink',
    column: 'border-good-line',
    drop: 'border-good-ink bg-good-soft',
  },
  D: {
    header: 'text-neutral-ink',
    chip: 'border-neutral-line bg-neutral-soft text-neutral-ink',
    column: 'border-neutral-line',
    drop: 'border-neutral-ink bg-neutral-soft',
  },
}

// A tier the config defines but this map does not must still render.
const fallbackTone = tierTones.D
function toneFor(tier) {
  return tierTones[tier] || fallbackTone
}

const roster = ref(null)
const rosterError = ref('')
// tier -> [school], the working copy the UI drags between.
const schoolGroups = ref({})
const newSchool = ref({})
const dragging = ref(null)
const dragOverTier = ref(null)

function baseTierOf(name) {
  if (!roster.value) return null
  for (const [tier, names] of Object.entries(roster.value)) {
    if (names.includes(name)) return tier
  }
  return null
}

function isMoved(name) {
  const base = baseTierOf(name)
  const current = currentTierOf(name)
  // A school absent from the roster is an operator addition, which is a change
  // by definition.
  return base === null ? true : base !== current
}

function currentTierOf(name) {
  for (const [tier, names] of Object.entries(schoolGroups.value)) {
    if (names.includes(name)) return tier
  }
  return null
}

const movedCount = computed(() =>
  Object.values(schoolGroups.value).flat().filter((n) => isMoved(n)).length
)

/** Build the editable groups from the roster plus saved overrides. */
function buildGroups() {
  const groups = {}
  for (const tier of schoolTierKeys.value) groups[tier] = []
  if (roster.value) {
    for (const [tier, names] of Object.entries(roster.value)) {
      if (!groups[tier]) groups[tier] = []
      groups[tier].push(...names)
    }
  }
  // Apply overrides: move a listed school, or add one the roster lacks.
  for (const row of cfg.value?.education?.school_overrides || []) {
    const name = (row.pattern || '').trim()
    const tier = (row.tier || '').trim().toUpperCase()
    if (!name || !groups[tier]) continue
    for (const key of Object.keys(groups)) {
      groups[key] = groups[key].filter((n) => n !== name)
    }
    groups[tier].push(name)
  }
  schoolGroups.value = groups
}

/** Write the groups back as the minimal override list. */
function syncOverrides() {
  const out = []
  for (const tier of Object.keys(schoolGroups.value)) {
    for (const name of schoolGroups.value[tier]) {
      if (baseTierOf(name) !== tier) out.push({ pattern: name, tier })
    }
  }
  // Longest name first: matching is substring and first-match-wins, so a more
  // specific school must be checked before one whose name it contains.
  out.sort((a, b) => b.pattern.length - a.pattern.length)
  cfg.value.education.school_overrides = out
}

// The C column holds ~68 schools inside a fixed-height scroll box, so a school
// appended to the end lands below the fold and reads as "it vanished". Landing
// it at the TOP keeps it where the eye already is, and `justLanded` rings it
// briefly so the move is visible even when the column did not need to scroll.
// A static ring rather than animate-pulse: in this app pulsing means "loading
// skeleton" (see ListView), which is the wrong signal for a completed move.
const justLanded = ref('')
let landedTimer = null
// Per-tier scroll containers, so a drop can reveal the top of the list when the
// operator had already scrolled down it.
const listEls = ref({})

function placeInTier(tier, name) {
  for (const key of Object.keys(schoolGroups.value)) {
    schoolGroups.value[key] = schoolGroups.value[key].filter((n) => n !== name)
  }
  schoolGroups.value[tier].unshift(name)
  syncOverrides()

  // The item is now first, but the column may still be scrolled where the
  // operator left it, which would hide the arrival just as the old append did.
  nextTick(() => {
    const el = listEls.value[tier]
    if (el) el.scrollTop = 0
  })

  justLanded.value = name
  clearTimeout(landedTimer)
  landedTimer = setTimeout(() => {
    // Only clear if nothing landed after this one, so a quick second drag
    // does not have its highlight cut short by the first one's timer.
    if (justLanded.value === name) justLanded.value = ''
  }, 1600)
}

function dropOnTier(tier) {
  const drag = dragging.value
  dragOverTier.value = null
  dragging.value = null
  if (!drag || drag.from === tier) return
  placeInTier(tier, drag.name)
}

function addSchool(tier) {
  const name = (newSchool.value[tier] || '').trim()
  if (!name) return
  if (currentTierOf(name) === tier) {
    // Already here: still flash it, otherwise typing an existing name looks
    // like nothing happened.
    newSchool.value[tier] = ''
    justLanded.value = name
    clearTimeout(landedTimer)
    landedTimer = setTimeout(() => {
      if (justLanded.value === name) justLanded.value = ''
    }, 1600)
    return
  }
  placeInTier(tier, name)
  newSchool.value[tier] = ''
}

function removeSchool(tier, name) {
  schoolGroups.value[tier] = schoolGroups.value[tier].filter((n) => n !== name)
  syncOverrides()
}

function resetSchoolTiers() {
  cfg.value.education.school_overrides = []
  buildGroups()
}

const weightTotal = computed(() =>
  weightKeys.value.reduce((s, k) => s + (Number(cfg.value.weights[k]) || 0), 0)
)
const weightOk = computed(() => Math.abs(weightTotal.value - 1) < 1e-6)
const dirty = computed(() => cfg.value && JSON.stringify(cfg.value) !== savedSnapshot.value)

function normalizeWeights() {
  const total = weightTotal.value
  if (!total) return
  weightKeys.value.forEach((k) => {
    cfg.value.weights[k] = Math.round((cfg.value.weights[k] / total) * 100) / 100
  })
  // Absorb rounding drift into the largest weight so the total lands exactly on 1.
  const drift = Math.round((1 - weightTotal.value) * 100) / 100
  if (drift) {
    const largest = weightKeys.value.reduce((a, b) =>
      cfg.value.weights[a] >= cfg.value.weights[b] ? a : b
    )
    cfg.value.weights[largest] = Math.round((cfg.value.weights[largest] + drift) * 100) / 100
  }
}

async function load() {
  loading.value = true
  loadError.value = false
  try {
    const d = await fetchScoringConfig()
    cfg.value = d.config
    defaults.value = d.defaults
    customized.value = d.customized
    if (!cfg.value.education.school_overrides) cfg.value.education.school_overrides = []
    savedSnapshot.value = JSON.stringify(d.config)

    // The roster only labels the groups; a failure here must not block the
    // rest of the page, so it degrades to whatever the overrides already name.
    try {
      roster.value = (await fetchSchoolRoster()).roster
    } catch (e) {
      rosterError.value = e?.message || '讀取失敗'
      roster.value = {}
    }
    buildGroups()
  } catch {
    loadError.value = true
  } finally {
    loading.value = false
  }
}

let validateTimer = null
watch(
  cfg,
  () => {
    if (!cfg.value) return
    savedMsg.value = ''
    clearTimeout(validateTimer)
    validateTimer = setTimeout(async () => {
      try {
        const r = await validateScoringConfig(cfg.value)
        errors.value = r.errors || []
      } catch {
        errors.value = []
      }
    }, 300)
  },
  { deep: true }
)

async function doSave() {
  saving.value = true
  savedMsg.value = ''
  try {
    const r = await saveScoringConfig(cfg.value)
    cfg.value = r.config
    savedSnapshot.value = JSON.stringify(r.config)
    customized.value = true
    savedMsg.value = '已儲存。重新執行評分後即會套用。'
  } catch (e) {
    errors.value = [e?.response?.data?.error || '儲存失敗']
  } finally {
    saving.value = false
  }
}

async function doReset() {
  saving.value = true
  try {
    const r = await resetScoringConfig()
    cfg.value = r.config
    if (!cfg.value.education.school_overrides) cfg.value.education.school_overrides = []
    savedSnapshot.value = JSON.stringify(r.config)
    buildGroups()
    customized.value = false
    preview.value = null
    savedMsg.value = '已還原為預設值。'
  } finally {
    saving.value = false
  }
}

async function runPreview() {
  previewing.value = true
  try {
    preview.value = await previewScoringConfig(cfg.value)
  } catch (e) {
    errors.value = [e?.response?.data?.error || '試算失敗']
  } finally {
    previewing.value = false
  }
}

load()
</script>
