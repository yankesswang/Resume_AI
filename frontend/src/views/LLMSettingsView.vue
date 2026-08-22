<template>
  <div class="h-full overflow-y-auto">
    <div class="mx-auto max-w-4xl px-6 py-8">
      <div class="mb-6 flex items-start gap-4">
        <div class="min-w-0">
          <h1 class="text-display font-bold text-ink">AI 模型設定</h1>
          <p class="mt-1 text-small text-ink-muted">
            評分要用哪個模型服務。對話與 Embedding 可以分開設定。
          </p>
        </div>
        <div class="ml-auto flex shrink-0 items-center gap-2">
          <button class="btn btn-ghost" :disabled="saving || loading" @click="doReset">回復預設</button>
          <button class="btn btn-primary" :disabled="saving || loading" @click="doSave">
            <RefreshCw v-if="saving" class="h-3.5 w-3.5 animate-spin" :stroke-width="2" />
            {{ saving ? '儲存中…' : '儲存' }}
          </button>
        </div>
      </div>

      <div
        v-if="message"
        :class="[
          'mb-4 flex items-start gap-2 rounded-control border px-3 py-2 text-small',
          messageOk
            ? 'border-good-line bg-good-soft text-good-ink'
            : 'border-bad-line bg-bad-soft text-bad-ink',
        ]"
      >
        <component
          :is="messageOk ? Check : AlertTriangle"
          class="mt-0.5 h-4 w-4 shrink-0"
          :stroke-width="2.5"
        />
        <span>{{ message }}</span>
      </div>

      <!-- First load gets the shape of the page, not a bare line of text: the
           two sections and their controls are a known layout, so a skeleton
           tells the operator what is arriving. -->
      <div v-if="loading" class="space-y-4">
        <div v-for="n in 2" :key="n" class="card overflow-hidden">
          <div class="h-12 animate-pulse bg-surface-2" />
          <div class="space-y-3 p-5">
            <div class="grid gap-2 sm:grid-cols-2">
              <div class="h-16 animate-pulse rounded-control bg-surface-2" />
              <div class="h-16 animate-pulse rounded-control bg-surface-2" />
            </div>
            <div class="h-10 w-2/3 animate-pulse rounded-control bg-surface-2" />
          </div>
        </div>
      </div>

      <template v-else>
        <section v-for="s in sections" :key="s.key" class="card mb-4 overflow-hidden">
          <!-- The header carries the section's live state. Previously you had
               to read the whole form to learn which provider was selected. -->
          <header class="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-line bg-surface-2 px-5 py-3.5">
            <h2 class="text-title font-semibold text-ink">{{ s.title }}</h2>
            <span class="chip border-line bg-surface text-ink-muted">
              {{ providerLabel(s.key) }}
            </span>
            <span
              v-if="testResult[s.key]"
              class="chip"
              :class="testResult[s.key].ok
                ? 'border-good-line bg-good-soft text-good-ink'
                : 'border-bad-line bg-bad-soft text-bad-ink'"
            >
              <component
                :is="testResult[s.key].ok ? Check : AlertTriangle"
                class="h-3 w-3"
                :stroke-width="2.5"
              />
              {{ testResult[s.key].ok ? '連線正常' : '連線失敗' }}
            </span>
            <p class="w-full text-micro text-ink-muted">{{ s.hint }}</p>
          </header>

          <div class="p-5">
            <!-- Provider picker: two cards rather than a <select>, because the
                 choice changes which fields below are meaningful. -->
            <div class="mb-5 grid gap-2 sm:grid-cols-2">
              <button
                v-for="p in providerOptions"
                :key="p.value"
                type="button"
                @click="setProvider(s.key, p.value)"
                :class="[
                  'flex items-start gap-2.5 rounded-control border px-3 py-2.5 text-left transition-colors',
                  config[s.key].provider === p.value
                    ? 'border-brand-line bg-brand-soft text-brand-ink'
                    : 'border-line bg-surface text-ink-muted hover:border-line-strong hover:text-ink',
                ]"
              >
                <component
                  :is="p.value === 'openai' ? Cloud : HardDrive"
                  class="mt-0.5 h-4 w-4 shrink-0"
                  :stroke-width="2"
                />
                <span class="min-w-0">
                  <span class="block text-small font-semibold">{{ p.label }}</span>
                  <span class="mt-0.5 block text-micro opacity-80">{{ p.description }}</span>
                </span>
              </button>
            </div>

            <div class="grid gap-4 sm:grid-cols-2">
              <div>
                <label :for="`${s.key}-url`" class="mb-1 flex items-center gap-1.5 text-micro font-medium text-ink-muted">
                  服務網址
                  <span v-if="isPinned(s.key, 'base_url')" class="chip border-warn-line bg-warn-soft text-warn-ink">
                    <Lock class="h-3 w-3" :stroke-width="2.5" />
                    環境變數
                  </span>
                </label>
                <input
                  :id="`${s.key}-url`"
                  :name="`${s.key}-base-url`" autocomplete="off" data-1p-ignore data-lpignore="true" spellcheck="false"
                  v-model="config[s.key].base_url"
                  :disabled="isPinned(s.key, 'base_url')"
                  :placeholder="defaultUrl(s.key)"
                  class="field w-full font-mono disabled:opacity-60"
                />
                <p class="mt-1 text-micro text-ink-faint">
                  點擊即可修改。只填主機位址（如 http://192.168.0.84:1234）也可以，留空則用預設值。
                </p>
              </div>

              <div>
                <label :for="`${s.key}-model`" class="mb-1 flex items-center gap-1.5 text-micro font-medium text-ink-muted">
                  模型名稱
                  <span v-if="isPinned(s.key, 'model')" class="chip border-warn-line bg-warn-soft text-warn-ink">
                    <Lock class="h-3 w-3" :stroke-width="2.5" />
                    環境變數
                  </span>
                </label>

                <!-- A cloud provider routes on the model name, so picking one
                     from a list is the normal case and typing one is the
                     exception. The dropdown carries a 自訂 option rather than
                     replacing the text field: OpenAI ships names faster than
                     this list is edited, and an operator who cannot type one
                     would be stuck waiting for a release. -->
                <select
                  v-if="modelOptions(s.key).length"
                  :id="`${s.key}-model`"
                  :name="`${s.key}-model-select`"
                  :value="isCustomModel(s.key) ? CUSTOM : config[s.key].model"
                  :disabled="isPinned(s.key, 'model')"
                  @change="onModelSelect(s.key, $event.target.value)"
                  class="field w-full disabled:opacity-60"
                >
                  <option
                    v-if="s.key === 'chat' && config[s.key].provider === 'lmstudio'"
                    value=""
                  >自動（使用地端已載入的模型）</option>
                  <option v-for="m in modelOptions(s.key)" :key="m.value" :value="m.value">
                    {{ m.label }}
                  </option>
                  <option :value="CUSTOM">自訂模型名稱…</option>
                </select>

                <input
                  v-if="!modelOptions(s.key).length || isCustomModel(s.key)"
                  :id="modelOptions(s.key).length ? `${s.key}-model-custom` : `${s.key}-model`"
                  :name="`${s.key}-model-name`" autocomplete="off" data-1p-ignore data-lpignore="true" spellcheck="false"
                  v-model="config[s.key].model"
                  :disabled="isPinned(s.key, 'model')"
                  :placeholder="modelPlaceholder(s.key)"
                  :class="[
                    'field w-full font-mono disabled:opacity-60',
                    modelOptions(s.key).length ? 'mt-2' : '',
                  ]"
                />

                <!-- The catalogue's per-model note. Shown only for a chosen
                     preset: cost and speed are what the choice actually turns
                     on, and burying them in a docs page means the operator
                     picks by name alone. -->
                <p v-if="selectedModelNote(s.key)" class="mt-1 text-micro text-ink-muted">
                  {{ selectedModelNote(s.key) }}
                </p>
                <!-- ...and the format rule in its place while typing one. -->
                <p v-else-if="isCustomModel(s.key)" class="mt-1 text-micro text-ink-muted">
                  {{ customModelHint(s.key) }}
                </p>
                <p class="mt-1 text-micro text-ink-faint">{{ modelHint(s.key) }}</p>
              </div>

              <!-- The key field is only meaningful for OpenAI. It stays
                   visible for a local server (some proxies want one) but drops
                   to half width and says so, instead of occupying a full row
                   of a form where it is usually irrelevant. -->
              <div :class="config[s.key].provider === 'openai' ? 'sm:col-span-2' : ''">
                <label :for="`${s.key}-key`" class="mb-1 block text-micro font-medium text-ink-muted">
                  API 金鑰
                  <span v-if="config[s.key].provider !== 'openai'" class="font-normal text-ink-faint">（地端通常免填）</span>
                </label>
                <input
                  :id="`${s.key}-key`"
                  v-model="config[s.key].api_key"
                  type="password"
                  :name="`${s.key}-api-key`"
                  autocomplete="new-password" data-1p-ignore data-lpignore="true" spellcheck="false"
                  :placeholder="hasSecret[s.key] ? '已設定，留空即不變更' : 'sk-…'"
                  class="field w-full font-mono"
                />
                <p v-if="config[s.key].provider === 'openai'" class="mt-1 text-micro text-ink-faint">
                  必填。金鑰存進資料庫後一律遮罩，不會再回傳明文。
                </p>
              </div>
            </div>

            <!-- Advanced numbers. Collapsed because they are correct by
                 default and are read far less often than the three fields
                 above; open automatically when the environment pins one, so a
                 read-only value is never hidden from the person wondering why
                 their edit does nothing. -->
            <details class="mt-4 border-t border-line pt-4" :open="hasPinnedAdvanced(s.key)">
              <summary class="flex cursor-pointer list-none items-center gap-1.5 text-small font-medium text-ink-muted transition-colors hover:text-ink">
                <ChevronRight class="h-3.5 w-3.5 transition-transform [details[open]_&]:rotate-90" :stroke-width="2" />
                進階參數
                <span class="text-micro font-normal text-ink-faint">{{ advancedSummary(s.key) }}</span>
              </summary>

              <div class="mt-3 grid gap-4 sm:grid-cols-2">
                <template v-if="s.key === 'chat'">
                  <div>
                    <label for="chat-ctx" class="mb-1 flex items-center gap-1.5 text-micro font-medium text-ink-muted">
                      context length
                      <span v-if="isPinned('chat', 'context_length')" class="chip border-warn-line bg-warn-soft text-warn-ink">
                        <Lock class="h-3 w-3" :stroke-width="2.5" />
                        環境變數
                      </span>
                    </label>
                    <input
                      id="chat-ctx"
                      name="chat-context-length" autocomplete="off" data-1p-ignore data-lpignore="true" spellcheck="false"
                      v-model.number="config.chat.context_length"
                      type="number"
                      min="1"
                      :disabled="isPinned('chat', 'context_length')"
                      class="field w-full disabled:opacity-60"
                    />
                    <p class="mt-1 text-micro text-ink-faint">
                      要和模型實際設定一致。設太低會把履歷默默截短。
                    </p>
                  </div>
                  <div>
                    <label for="chat-resp" class="mb-1 flex items-center gap-1.5 text-micro font-medium text-ink-muted">
                      回覆保留 tokens
                      <span v-if="isPinned('chat', 'response_tokens')" class="chip border-warn-line bg-warn-soft text-warn-ink">
                        <Lock class="h-3 w-3" :stroke-width="2.5" />
                        環境變數
                      </span>
                    </label>
                    <input
                      id="chat-resp"
                      name="chat-response-tokens" autocomplete="off" data-1p-ignore data-lpignore="true" spellcheck="false"
                      v-model.number="config.chat.response_tokens"
                      type="number"
                      min="1"
                      :disabled="isPinned('chat', 'response_tokens')"
                      class="field w-full disabled:opacity-60"
                    />
                    <p class="mt-1 text-micro text-ink-faint">從 context 裡留給模型回答的額度。</p>
                  </div>
                </template>

                <div>
                  <label :for="`${s.key}-timeout`" class="mb-1 block text-micro font-medium text-ink-muted">逾時（秒）</label>
                  <input
                    :id="`${s.key}-timeout`"
                    :name="`${s.key}-timeout`" autocomplete="off" data-1p-ignore data-lpignore="true" spellcheck="false"
                    v-model.number="config[s.key].timeout"
                    type="number"
                    min="1"
                    class="field w-full"
                  />
                </div>
              </div>
            </details>

            <!-- Connection test: the only thing on this page that proves the
                 settings actually work before a scoring run depends on them. -->
            <div class="mt-4 border-t border-line pt-4">
              <div class="flex flex-wrap items-center gap-3">
                <button class="btn btn-on" :disabled="testing[s.key]" @click="doTest(s.key)">
                  <RefreshCw v-if="testing[s.key]" class="h-3.5 w-3.5 animate-spin" :stroke-width="2" />
                  <Plug v-else class="h-3.5 w-3.5" :stroke-width="2" />
                  {{ testing[s.key] ? '測試中…' : '測試連線' }}
                </button>

                <p v-if="!testResult[s.key]" class="text-micro text-ink-faint">
                  送出一次極短的請求，一次驗證網址、金鑰與模型名稱。
                </p>

                <!-- A failure is the case the operator has to act on, so the
                     message is given room rather than trailing off one line. -->
                <p v-else-if="testResult[s.key].ok" class="text-small text-good-ink">
                  連線成功
                  <span class="text-ink-muted">
                    · {{ testResult[s.key].model || '未指名模型' }}
                    · {{ testResult[s.key].elapsed_ms }} ms
                    <template v-if="testResult[s.key].dimensions">
                      · {{ testResult[s.key].dimensions }} 維
                    </template>
                  </span>
                </p>
              </div>

              <p
                v-if="testResult[s.key] && !testResult[s.key].ok"
                class="mt-2 rounded-control border border-bad-line bg-bad-soft px-3 py-2 text-small break-words text-bad-ink"
              >{{ testResult[s.key].error }}</p>
            </div>
          </div>
        </section>

        <section class="card mb-4 overflow-hidden">
          <header class="border-b border-line bg-surface-2 px-5 py-3.5">
            <h2 class="text-title font-semibold text-ink">目前生效的設定</h2>
          </header>
          <div class="p-5">
            <dl class="grid gap-3 text-small sm:grid-cols-2">
              <div v-for="s in sections" :key="s.key">
                <dt class="text-micro font-medium text-ink-muted">{{ s.title }}</dt>
                <dd class="mt-0.5 break-all font-mono text-ink">{{ resolved[s.key] }}</dd>
              </div>
            </dl>

            <!-- Two facts that surprise people, kept as short labelled rows
                 rather than the two dense paragraphs that were here before. -->
            <dl class="mt-5 space-y-2.5 border-t border-line pt-4 text-micro">
              <div class="flex flex-wrap items-baseline gap-x-2">
                <dt class="font-semibold text-ink">設定優先序</dt>
                <dd class="text-ink-muted">
                  環境變數 &gt; 這個頁面 &gt; 內建預設。被鎖定的欄位改了不會生效，所以直接標成唯讀。
                </dd>
              </div>
              <div class="flex flex-wrap items-baseline gap-x-2">
                <dt class="font-semibold text-ink">換模型會怎樣</dt>
                <dd class="text-ink-muted">
                  已快取的 AI 分級會失效（不同模型的判斷不能互用），到
                  <router-link to="/scoring" class="text-brand-ink underline">評分設定</router-link>
                  重新評分即可。只換金鑰不影響快取。
                </dd>
              </div>
            </dl>
          </div>
        </section>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import {
  fetchLLMConfig,
  saveLLMConfig,
  resetLLMConfig,
  testLLMConfig,
} from '../api'
import { AlertTriangle, Check, ChevronRight, Cloud, HardDrive, Lock, Plug, RefreshCw } from 'lucide-vue-next'

const loading = ref(true)
const saving = ref(false)
const message = ref('')
const messageOk = ref(true)

const config = reactive({
  chat: {
    provider: 'lmstudio',
    base_url: '',
    model: '',
    api_key: '',
    context_length: 32768,
    response_tokens: 2048,
    timeout: 300,
  },
  embedding: {
    provider: 'lmstudio',
    base_url: '',
    model: '',
    api_key: '',
    timeout: 10,
  },
})

const envPinned = ref({ chat: [], embedding: [] })
// Suggested model names per provider/section, served by GET /api/llm-config.
// Empty until the first load, which is why modelOptions() tolerates a missing
// provider key rather than assuming the shape is there.
const modelCatalogue = ref({})
// Sentinel for the dropdown's "type your own" row. A value no model can have,
// so it can never collide with a real name arriving from the catalogue.
const CUSTOM = '__custom__'
const hasSecret = ref({ chat: false, embedding: false })
const resolved = ref({ chat: '', embedding: '' })
const testing = reactive({ chat: false, embedding: false })
const testResult = reactive({ chat: null, embedding: null })

const sections = [
  {
    key: 'chat',
    title: '對話模型',
    hint: '負責履歷結構化解析、AI 分級判斷、以及從 JD 產生評分標準。',
  },
  {
    key: 'embedding',
    title: 'Embedding 模型',
    hint: '負責語意相似度（履歷與職缺的向量比對），佔總分 20%。',
  },
]

const providerOptions = [
  {
    value: 'lmstudio',
    // "地端模型" rather than "LM Studio": this path speaks plain
    // OpenAI-compatible HTTP, so Ollama / vLLM / llama.cpp all work here and
    // naming one vendor made the other three look unsupported. The stored
    // value stays 'lmstudio' — it is the API contract, and renaming it would
    // invalidate every saved config.
    label: '地端模型',
    description: '在自己機器上跑的模型服務（LM Studio、Ollama、vLLM 等相容 OpenAI 格式者），資料不出機器。',
  },
  {
    value: 'openai',
    label: 'OpenAI API',
    description: '雲端服務，需要 API 金鑰，履歷內容會送往 OpenAI。',
  },
]

function defaultUrl(section) {
  const openai = config[section].provider === 'openai'
  if (section === 'chat') {
    return openai
      ? 'https://api.openai.com/v1/chat/completions'
      : 'http://localhost:1234/v1/chat/completions'
  }
  return openai
    ? 'https://api.openai.com/v1/embeddings'
    : 'http://localhost:1234/v1/embeddings'
}

function modelOptions(section) {
  const provider = config[section].provider
  return modelCatalogue.value?.[provider]?.[section] || []
}

// "Custom" is a state of the *value*, not a separate flag: a model name that is
// not in the catalogue can only be shown in the text field, and deriving that
// keeps the two controls from disagreeing after a load or a provider switch.
function isCustomModel(section) {
  const options = modelOptions(section)
  if (!options.length) return true
  const current = config[section].model
  if (!current) {
    // Blank is a legitimate "use the loaded model" for a local chat server, and
    // that has its own option; anywhere else a blank field is an unfinished
    // custom entry rather than a chosen model.
    return !(section === 'chat' && config[section].provider === 'lmstudio')
  }
  return !options.some((m) => m.value === current)
}

function selectedModelNote(section) {
  if (isCustomModel(section)) return ''
  const found = modelOptions(section).find((m) => m.value === config[section].model)
  return found?.description || ''
}

function onModelSelect(section, value) {
  // Switching *to* 自訂 clears the field so the operator types into an empty
  // box; keeping the previously selected name would look like the dropdown had
  // not changed anything.
  config[section].model = value === CUSTOM ? '' : value
  testResult[section] = null
}

// The placeholder is an *example of the format*, not an instruction. The text
// field now only appears after the operator picked 自訂, i.e. they already know
// they are typing a name — what they need at that moment is the shape the local
// server prints in its own UI, which is where they will copy the name from.
function modelPlaceholder(section) {
  const openai = config[section].provider === 'openai'
  if (section === 'chat') return openai ? 'gpt-4o-mini' : 'qwen2.5-7b-instruct'
  return openai ? 'text-embedding-3-small' : 'text-embedding-nomic-embed-text-v1.5'
}

// Shown under the free-text box only. A local server matches on the identifier
// the local server itself displays, and getting it wrong fails at request time with a
// model-not-found rather than here — so the rule for reading that identifier is
// worth stating at the moment someone is typing one.
function customModelHint(section) {
  if (config[section].provider === 'openai') {
    return '請填 OpenAI 的模型 ID，例如 gpt-4o-mini、o4-mini。'
  }
  return section === 'chat'
    ? '填地端服務上的模型識別碼，通常是「系列-參數量-用途」，例如 qwen2.5-7b-instruct。留空則用目前載入的模型。'
    : '填地端服務上的 embedding 模型識別碼，例如 text-embedding-nomic-embed-text-v1.5。'
}

function modelHint(section) {
  const listed = modelOptions(section).length > 0
  if (section === 'chat') {
    if (config.chat.provider === 'openai') {
      return listed
        ? 'OpenAI 依模型名稱路由，必填。清單是建議值，未列出的新模型可選「自訂」自行輸入。'
        : 'OpenAI 依模型名稱路由，必填。'
    }
    return listed
      ? '留空則使用地端服務目前載入的模型；清單是常見的地端模型格式參考，實際名稱以你下載的為準。'
      : '留空則使用地端服務目前載入的模型。'
  }
  return listed
    ? 'Embedding 一律需要指定模型名稱；未列出的模型可選「自訂」自行輸入。'
    : 'Embedding 一律需要指定模型名稱。'
}

function providerLabel(section) {
  const found = providerOptions.find((p) => p.value === config[section].provider)
  return found ? found.label : config[section].provider
}

// Fields inside the collapsed 進階參數 block. Listed here so the disclosure can
// open itself when the environment owns one of them: a value the operator
// cannot change is exactly the one they need to see before they go looking for
// why their edit had no effect.
const ADVANCED_FIELDS = {
  chat: ['context_length', 'response_tokens'],
  embedding: [],
}

function hasPinnedAdvanced(section) {
  return ADVANCED_FIELDS[section].some((f) => isPinned(section, f))
}

// A closed disclosure must still say what it is hiding, or it reads as an
// empty control and nobody opens it.
function advancedSummary(section) {
  if (section === 'chat') {
    return `context ${config.chat.context_length} · 回覆 ${config.chat.response_tokens} · 逾時 ${config.chat.timeout}s`
  }
  return `逾時 ${config[section].timeout}s`
}

function isPinned(section, field) {
  return (envPinned.value[section] || []).includes(field)
}

function setProvider(section, value) {
  if (config[section].provider === value) return
  const previous = config[section].provider
  config[section].provider = value
  // A base_url belonging to the other provider must not survive the switch:
  // keeping "http://localhost:1234/..." after moving to OpenAI would send the
  // request to the wrong host and read as a broken switch. The new provider's
  // default is filled in rather than left blank, so the box keeps showing the
  // URL that will actually be called.
  if (!isPinned(section, 'base_url')) config[section].base_url = defaultUrl(section)
  // Same reasoning for the model. A local model name means nothing to OpenAI
  // (and vice versa), so carrying it across is a request that always 404s.
  // The new provider's first suggestion is filled in instead of a blank,
  // because a blank model is invalid for OpenAI and for every embedding
  // section — the form would arrive unsaveable.
  if (!isPinned(section, 'model')) {
    const carried = config[section].model
    const wasListed = (modelCatalogue.value?.[previous]?.[section] || [])
      .some((m) => m.value === carried)
    // A hand-typed name is the operator's own, so it survives the switch and
    // shows up in the 自訂 field; only a name they picked off the old
    // provider's list is replaced.
    if (!carried || wasListed) {
      config[section].model = defaultModel(section, value)
    }
  }
  testResult[section] = null
}

// What to pre-fill when a provider switch invalidates the current model.
// Mirrors llm_config.default_model(): a local chat model stays blank even
// though the catalogue lists names, because blank means "use whatever the local
// server has loaded" — valid, and right more often than any single name. Those entries
// are format references for someone typing their own, not a claim about what is
// installed, so pre-selecting one would name a model they may not have.
function defaultModel(section, providerName) {
  if (providerName === 'lmstudio' && section === 'chat') return ''
  const options = modelCatalogue.value?.[providerName]?.[section] || []
  return options.length ? options[0].value : ''
}

function apply(data) {
  const incoming = data.config || {}
  for (const key of ['chat', 'embedding']) {
    Object.assign(config[key], incoming[key] || {})
    // The server sends a mask, never the key. Blank the field so the operator
    // types a new key only when they mean to replace it; an untouched blank
    // means "keep what is stored".
    config[key].api_key = ''
  }
  if (data.model_catalogue) modelCatalogue.value = data.model_catalogue
  envPinned.value = data.env_pinned || { chat: [], embedding: [] }
  if (data.has_secret) hasSecret.value = data.has_secret
  if (data.resolved) resolved.value = data.resolved

  // A stored-blank base_url means "use the provider's default", which rendered
  // as an empty box with grey placeholder text — indistinguishable from "not
  // configured", and nothing to click into and edit. Fill it with the URL the
  // server says it is actually calling (`resolved`), so the field shows the
  // real setting and is editable in place.
  //
  // `resolved` rather than defaultUrl(): the server has already applied the
  // env overlay and its own path-completion, so this cannot show a different
  // URL from the one the requests go to.
  for (const key of ['chat', 'embedding']) {
    if (!config[key].base_url && data.resolved?.[key]) {
      config[key].base_url = data.resolved[key]
    }
  }
}

// Only send a key when one was typed: an empty string would erase the stored
// credential, and the placeholder promises it will not.
function payload() {
  const out = {}
  for (const key of ['chat', 'embedding']) {
    const { api_key, ...rest } = config[key]
    out[key] = { ...rest }
    if (api_key) out[key].api_key = api_key
  }
  return out
}

function flash(text, ok = true) {
  message.value = text
  messageOk.value = ok
}

async function load() {
  loading.value = true
  try {
    apply(await fetchLLMConfig())
  } catch (e) {
    flash(errorText(e, '載入設定失敗'), false)
  } finally {
    loading.value = false
  }
}

async function doSave() {
  saving.value = true
  message.value = ''
  try {
    const data = await saveLLMConfig(payload())
    apply(data)
    hasSecret.value = {
      chat: hasSecret.value.chat || !!data.config?.chat?.api_key,
      embedding: hasSecret.value.embedding || !!data.config?.embedding?.api_key,
    }
    flash('已儲存，下一次評分即套用。')
  } catch (e) {
    flash(errorText(e, '儲存失敗'), false)
  } finally {
    saving.value = false
  }
}

async function doReset() {
  if (!window.confirm('回復內建預設值？已儲存的 API 金鑰會一併清除。')) return
  saving.value = true
  try {
    apply(await resetLLMConfig())
    hasSecret.value = { chat: false, embedding: false }
    testResult.chat = null
    testResult.embedding = null
    flash('已回復預設值。')
  } catch (e) {
    flash(errorText(e, '回復失敗'), false)
  } finally {
    saving.value = false
  }
}

async function doTest(section) {
  testing[section] = true
  testResult[section] = null
  try {
    testResult[section] = await testLLMConfig(payload(), section)
  } catch (e) {
    testResult[section] = { ok: false, error: errorText(e, '測試失敗') }
  } finally {
    testing[section] = false
  }
}

function errorText(e, fallback) {
  return e?.response?.data?.error || e?.message || fallback
}

onMounted(load)
</script>
