<template>
  <div class="flex h-full flex-col overflow-hidden">
    <!-- Toolbar -->
    <div class="flex shrink-0 items-center justify-between border-b border-line bg-surface px-5 py-3">
      <div class="flex min-w-0 items-center gap-2 text-small text-ink-muted">
        <router-link to="/jobs" class="text-ink-muted no-underline hover:text-ink">職缺管理</router-link>
        <span class="text-ink-faint">/</span>
        <span class="truncate font-semibold text-ink">{{ jobTitle }}</span>
        <span v-if="dirty" class="text-ink-faint">·</span>
        <span v-if="dirty" class="font-semibold text-brand-ink">尚未儲存</span>
      </div>
      <div class="flex items-center gap-2">
        <button
          @click="runPreview"
          :disabled="previewing || !profile"
          class="rounded-control border border-line px-3 py-1.5 text-micro font-semibold text-ink-muted transition hover:border-line-strong hover:text-ink disabled:opacity-50"
        >
          {{ previewing ? '試算中…' : '試算篩選結果' }}
        </button>
        <button
          @click="doRegenerate"
          :disabled="regenerating || saving"
          class="rounded-control border border-line px-3 py-1.5 text-micro font-semibold text-ink-muted transition hover:border-line-strong disabled:opacity-50"
        >
          {{ regenerating ? '重新生成中…' : '重新生成' }}
        </button>
        <button
          @click="doSave(false)"
          :disabled="saving || !profile"
          class="rounded-control border border-line px-3 py-1.5 text-micro font-semibold text-ink-muted transition hover:border-line-strong disabled:opacity-50"
        >
          儲存草稿
        </button>
        <button
          @click="doSave(true)"
          :disabled="saving || !profile || !!errors.length"
          class="rounded-control bg-brand px-4 py-1.5 text-micro font-semibold text-white transition hover:bg-brand-hover disabled:opacity-40"
        >
          {{ saving ? '儲存中…' : '確認並啟用' }}
        </button>
      </div>
    </div>

    <div class="flex-1 overflow-auto p-5">
      <div v-if="loading" class="py-20 text-center text-small text-ink-faint">載入中…</div>

      <div v-else-if="loadError" class="py-20 text-center">
        <h3 class="mb-3 text-small font-semibold text-ink">{{ loadError }}</h3>
        <button @click="load" class="rounded-control bg-brand px-4 py-2 text-small font-semibold text-white">重試</button>
      </div>

      <div v-else-if="!profile" class="mx-auto max-w-3xl py-16 text-center">
        <p class="text-small text-ink-muted">這個職缺還沒有評分標準。</p>
        <button
          @click="doRegenerate"
          :disabled="regenerating"
          class="mt-3 rounded-control bg-brand px-4 py-2 text-small font-semibold text-white disabled:opacity-40"
        >
          {{ regenerating ? '生成中…' : '從職缺內容生成' }}
        </button>
      </div>

      <div v-else class="mx-auto max-w-5xl space-y-5">
        <!-- Review banner: a generated standard is a draft until a person reads it -->
        <div
          v-if="profileStatus === 'draft'"
          class="rounded-card border border-warn-line bg-warn-soft p-4"
        >
          <p class="text-small font-semibold text-warn-ink">這是自動產生的草稿，尚未套用</p>
          <p class="mt-1 text-micro leading-relaxed text-warn-ink">
            請逐項檢查下方的分級定義與關鍵字是否符合這個職位的實際情況。
            建議先「試算篩選結果」，確認在現有履歷池中能區分出高低，再按「確認並啟用」。
          </p>
        </div>

        <div v-if="errors.length" class="rounded-card border border-bad-line bg-bad-soft p-4">
          <p class="mb-1.5 text-small font-semibold text-bad-ink">評分標準有問題，無法啟用</p>
          <ul class="list-inside list-disc space-y-1 text-micro text-bad-ink">
            <li v-for="(e, i) in errors" :key="i">{{ e }}</li>
          </ul>
        </div>
        <div v-if="savedMsg" class="rounded-card border border-good-line bg-good-soft p-3 text-small text-good-ink">
          {{ savedMsg }}
        </div>

        <!-- Parsed JD. Shown above the standard because the standard is derived
             from it: a reviewer checking a keyword needs the source in reach. -->
        <section v-if="job" class="overflow-hidden rounded-card border border-line bg-surface">
          <button
            class="flex w-full items-center justify-between gap-3 px-5 py-3 text-left transition-colors hover:bg-surface-2"
            :aria-expanded="showParsed"
            @click="showParsed = !showParsed"
          >
            <span class="min-w-0">
              <span class="block text-small font-semibold text-ink">職缺文件解析結果</span>
              <span class="mt-0.5 block truncate text-micro text-ink-muted">
                {{ sourceDocument || '手動輸入' }}
                <template v-if="job.domain"> · {{ job.domain }}</template>
              </span>
            </span>
            <ChevronDown class="h-4 w-4 shrink-0 text-ink-faint transition-transform" :class="{ 'rotate-180': showParsed }" :stroke-width="2" />
          </button>

          <div v-if="showParsed" class="border-t border-line px-5 py-4">
            <p v-if="job.job_summary" class="mb-4 text-base leading-relaxed text-ink">
              {{ job.job_summary }}
            </p>

            <div class="grid grid-cols-1 gap-4 md:grid-cols-2">
              <div v-if="basicRows.length">
                <h3 class="mb-2 text-micro font-semibold text-ink-muted">基本條件</h3>
                <dl class="space-y-1.5">
                  <div v-for="[label, value] in basicRows" :key="label" class="flex gap-2">
                    <dt class="w-20 shrink-0 text-small text-ink-faint">{{ label }}</dt>
                    <dd class="min-w-0 flex-1 text-small text-ink">{{ value }}</dd>
                  </div>
                </dl>
              </div>

              <div v-if="requirementRows.length">
                <h3 class="mb-2 text-micro font-semibold text-ink-muted">應徵條件</h3>
                <dl class="space-y-1.5">
                  <div v-for="[label, value] in requirementRows" :key="label" class="flex gap-2">
                    <dt class="w-20 shrink-0 text-small text-ink-faint">{{ label }}</dt>
                    <dd class="min-w-0 flex-1 text-small leading-relaxed text-ink">{{ value }}</dd>
                  </div>
                </dl>
              </div>
            </div>

            <div v-if="responsibilities.length" class="mt-4">
              <h3 class="mb-2 text-micro font-semibold text-ink-muted">工作內容</h3>
              <div class="space-y-3">
                <div v-for="(group, gi) in responsibilities" :key="gi">
                  <p v-if="group.category" class="text-small font-semibold text-ink">{{ group.category }}</p>
                  <ul class="mt-1 list-outside list-disc space-y-1 pl-5 text-small leading-relaxed text-ink-muted">
                    <li v-for="(item, ii) in group.items" :key="ii">{{ item }}</li>
                  </ul>
                </div>
              </div>
            </div>

            <div v-if="preferred.length" class="mt-4">
              <h3 class="mb-2 text-micro font-semibold text-ink-muted">加分條件</h3>
              <ul class="list-outside list-disc space-y-1 pl-5 text-small leading-relaxed text-ink-muted">
                <li v-for="(item, i) in preferred" :key="i">{{ item }}</li>
              </ul>
            </div>
          </div>
        </section>

        <!-- Preview results -->
        <section v-if="preview" class="rounded-card border border-line bg-surface p-5">
          <header class="mb-3">
            <h2 class="text-small font-semibold text-ink">試算結果</h2>
            <p class="mt-0.5 text-micro text-ink-muted">
              以現有履歷池 {{ preview.sample_size }} 份履歷試算（僅關鍵字比對，不呼叫 AI 模型）
            </p>
          </header>
          <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div v-for="s in previewStats" :key="s.label" class="rounded-control bg-surface-2 px-3 py-2">
              <p class="text-micro text-ink-muted">{{ s.label }}</p>
              <p class="text-small font-semibold text-ink">{{ s.value }}</p>
            </div>
          </div>
          <div class="mt-3 flex flex-wrap gap-2">
            <span
              v-for="(count, tier) in preview.tier_distribution"
              :key="tier"
              class="chip border-line bg-surface-2 text-ink-muted"
            >
              Tier {{ tier }} · {{ tierLabel(Number(tier)) }}：{{ count }} 人
            </span>
          </div>
          <div
            v-for="(w, i) in preview.warnings"
            :key="i"
            class="mt-3 rounded-card border border-warn-line bg-warn-soft p-3 text-micro leading-relaxed text-warn-ink"
          >
            {{ w }}
          </div>
          <table class="mt-4 w-full text-micro">
            <thead>
              <tr class="border-b border-line text-left text-ink-muted">
                <th class="py-1.5 font-medium">候選人</th>
                <th class="py-1.5 font-medium">分數</th>
                <th class="py-1.5 font-medium">級距</th>
                <th class="py-1.5 font-medium">硬性條件</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in preview.results.slice(0, 12)" :key="r.id" class="border-b border-line/50">
                <td class="py-1.5 text-ink">{{ r.name || `#${r.id}` }}</td>
                <td class="py-1.5 font-semibold text-ink">{{ r.score }}</td>
                <td class="py-1.5 text-ink-muted">{{ r.tier_label }}</td>
                <td class="py-1.5">
                  <span v-if="r.passed_hard_filter" class="text-good-ink">通過</span>
                  <span v-else class="text-bad-ink" :title="r.hard_filter_failures.join('; ')">未通過</span>
                </td>
              </tr>
            </tbody>
          </table>
        </section>

        <!-- Basics -->
        <section class="rounded-card border border-line bg-surface p-5">
          <h2 class="text-small font-semibold text-ink">基本資訊</h2>
          <div class="mt-3 space-y-3">
            <label class="block">
              <span class="mb-1 block text-micro font-medium text-ink-muted">職缺名稱</span>
              <input v-model="profile.name" class="w-full field px-3 py-2 text-micro" />
            </label>
            <label class="block">
              <span class="mb-1 block text-micro font-medium text-ink-muted">專業領域</span>
              <input v-model="profile.domain" class="w-full field px-3 py-2 text-micro" />
            </label>
            <label class="block">
              <span class="mb-1 block text-micro font-medium text-ink-muted">職位說明（會提供給 AI 分級器）</span>
              <textarea
                v-model="profile.summary"
                rows="2"
                class="w-full field px-3 py-2 text-micro leading-relaxed"
              ></textarea>
            </label>
          </div>
        </section>

        <!-- Tiers -->
        <section class="rounded-card border border-line bg-surface p-5">
          <header class="mb-3">
            <h2 class="text-small font-semibold text-ink">深度分級</h2>
            <p class="mt-0.5 text-micro leading-relaxed text-ink-muted">
              這是評分中權重最高的構面。「判斷依據」會原封不動送給 AI 分級器，
              請寫「該看到什麼證據」，而不是抽象形容詞。
            </p>
          </header>
          <div class="space-y-3">
            <div v-for="t in profile.tiers" :key="t.level" class="rounded-control border border-line p-3">
              <div class="flex items-center gap-2">
                <span class="chip border-line bg-surface-2 text-ink-muted">Tier {{ t.level }}</span>
                <input
                  v-model="t.label"
                  placeholder="級距名稱"
                  class="flex-1 field px-2 py-1 text-micro font-semibold"
                />
              </div>
              <textarea
                v-model="t.definition"
                rows="2"
                placeholder="判斷依據：履歷中要看到什麼，才算這一級？"
                class="mt-2 w-full field px-2 py-1.5 text-micro leading-relaxed"
              ></textarea>
              <input
                :value="(t.evidence_examples || []).join('、')"
                @input="t.evidence_examples = splitList($event.target.value)"
                placeholder="典型證據（用、分隔）"
                class="mt-2 w-full field px-2 py-1 text-micro"
              />
            </div>
          </div>
        </section>

        <!-- Tier keywords -->
        <section class="rounded-card border border-line bg-surface p-5">
          <header class="mb-3">
            <h2 class="text-small font-semibold text-ink">分級關鍵字</h2>
            <p class="mt-0.5 text-micro leading-relaxed text-ink-muted">
              履歷中可字面比對的字詞（工具、制度、方法、證照）。AI 模型無法使用時，
              評分完全依賴這裡。權重 0.5-2.5，越難造假的訊號給越高。
              格式：<code class="text-ink">關鍵字:權重</code>，每行一個。
            </p>
          </header>
          <div class="grid gap-3 md:grid-cols-3">
            <div v-for="lvl in ['1', '2', '3']" :key="lvl">
              <div class="mb-1 flex items-center justify-between">
                <span class="text-micro font-medium text-ink-muted">Tier {{ lvl }} · {{ tierLabel(Number(lvl)) }}</span>
                <span
                  class="text-micro"
                  :class="keywordCount(lvl) < 4 ? 'text-bad-ink font-semibold' : 'text-ink-faint'"
                >
                  {{ keywordCount(lvl) }} 個
                </span>
              </div>
              <textarea
                :value="keywordText[lvl]"
                @input="onKeywordInput(lvl, $event.target.value)"
                rows="10"
                class="w-full field px-2 py-1.5 font-mono text-micro leading-relaxed"
                placeholder="IFRS:2.0&#10;稅務簽證:2.2"
              ></textarea>
            </div>
          </div>
        </section>

        <!-- Competencies -->
        <section class="rounded-card border border-line bg-surface p-5">
          <header class="mb-3 flex items-start justify-between gap-3">
            <div>
              <h2 class="text-small font-semibold text-ink">能力面向</h2>
              <p class="mt-0.5 text-micro leading-relaxed text-ink-muted">
                這個職位需要的能力軸線，每軸依關鍵字判斷 0-3 級。權重會自動正規化。
              </p>
            </div>
            <button
              @click="addCompetency"
              class="shrink-0 rounded-control border border-line px-2.5 py-1 text-micro font-semibold text-ink-muted hover:border-line-strong"
            >
              新增面向
            </button>
          </header>
          <div class="space-y-3">
            <div v-for="(c, ci) in profile.competencies" :key="ci" class="rounded-control border border-line p-3">
              <div class="flex items-center gap-2">
                <input v-model="c.label" placeholder="面向名稱" class="flex-1 field px-2 py-1 text-micro font-semibold" />
                <input v-model="c.key" placeholder="key" class="w-28 field px-2 py-1 font-mono text-micro" />
                <input
                  v-model.number="c.weight"
                  type="number" min="0" max="1" step="0.05"
                  class="w-20 field px-2 py-1 text-right text-micro"
                />
                <button
                  @click="profile.competencies.splice(ci, 1)"
                  class="field px-2 py-1 text-micro text-ink-muted hover:border-bad-line hover:text-bad-ink"
                >
                  移除
                </button>
              </div>
              <div class="mt-2 grid gap-2 md:grid-cols-3">
                <label v-for="lvl in ['1', '2', '3']" :key="lvl" class="block">
                  <span class="mb-0.5 block text-micro text-ink-muted">Level {{ lvl }}</span>
                  <input
                    :value="(c.levels[lvl] || []).join('、')"
                    @input="c.levels[lvl] = splitList($event.target.value)"
                    class="w-full field px-2 py-1 text-micro"
                  />
                </label>
              </div>
            </div>
          </div>
        </section>

        <!-- Education + weights -->
        <div class="grid gap-4 md:grid-cols-2">
          <section class="rounded-card border border-line bg-surface p-5">
            <h2 class="text-small font-semibold text-ink">學歷科系</h2>
            <label class="mt-3 flex items-center gap-2 text-micro text-ink-muted">
              <input type="checkbox" v-model="profile.education.matters" class="accent-brand" />
              這個職位需要看學歷科系
            </label>
            <!-- Chosen majors first: the selection is the answer, the
                 catalogue below is only how you reach it. -->
            <div v-for="lane in majorLanes" :key="lane.key" class="mt-3">
              <div class="flex items-baseline justify-between gap-2">
                <span class="text-micro font-medium text-ink-muted">{{ lane.label }}</span>
                <span class="text-micro text-ink-faint">{{ (profile.education[lane.key] || []).length }} 項</span>
              </div>
              <div class="mt-1 flex flex-wrap gap-1 rounded-control border border-line bg-surface-2 p-2 min-h-9">
                <span
                  v-for="m in profile.education[lane.key] || []"
                  :key="m"
                  class="inline-flex items-center gap-1 rounded-control border px-1.5 py-0.5 text-micro"
                  :class="lane.tone"
                >
                  {{ m }}
                  <button @click="removeMajor(lane.key, m)" class="text-ink-faint hover:text-bad-ink">×</button>
                </span>
                <span v-if="!(profile.education[lane.key] || []).length" class="text-micro text-ink-faint">
                  尚未選擇
                </span>
              </div>
              <form @submit.prevent="addMajor(lane.key, newMajor[lane.key]); newMajor[lane.key] = ''" class="mt-1 flex gap-1">
                <input
                  v-model="newMajor[lane.key]"
                  placeholder="自行輸入科系後按 Enter"
                  class="min-w-0 flex-1 field px-2 py-1 text-micro"
                />
                <button type="submit" class="rounded-control border border-line px-2 py-1 text-micro text-ink-muted hover:border-line-strong">
                  +
                </button>
              </form>
            </div>

            <!-- Catalogue: click a major to file it into a lane. Clicking one
                 already chosen removes it, so the same click undoes a mistake. -->
            <div class="mt-4 border-t border-line pt-3">
              <div class="flex items-center justify-between gap-2">
                <span class="text-micro font-medium text-ink-muted">常見科系</span>
                <div class="flex items-center gap-1">
                  <button
                    v-for="lane in majorLanes"
                    :key="lane.key"
                    @click="majorTarget = lane.key"
                    class="rounded-control border px-2 py-0.5 text-micro"
                    :class="majorTarget === lane.key ? lane.tone : 'border-line text-ink-muted'"
                  >
                    加到{{ lane.short }}
                  </button>
                </div>
              </div>
              <p v-if="catalogueError" class="mt-2 text-micro text-ink-faint">
                無法載入常見科系（{{ catalogueError }}），可直接手動輸入。
              </p>
              <div v-for="(list, field) in majorCatalogue" :key="field" class="mt-2">
                <div class="flex items-center gap-2">
                  <p class="text-micro text-ink-faint">{{ field }}</p>
                  <!-- Bulk action: 14 chips in 資訊 alone is a lot of clicking.
                       Flips to "remove all" once the whole group is in the
                       target lane, so the same control undoes itself. -->
                  <button
                    @click="toggleGroup(field, list)"
                    class="rounded-control border border-line px-1.5 py-0.5 text-micro text-ink-muted hover:border-line-strong"
                  >
                    {{ groupFullyIn(list) ? '全部移除' : `全選加到${laneLabel(majorTarget, true)}` }}
                  </button>
                  <span v-if="groupSelectedCount(list)" class="text-micro text-ink-faint">
                    已選 {{ groupSelectedCount(list) }}/{{ list.length }}
                  </span>
                </div>
                <div class="mt-1 flex flex-wrap gap-1">
                  <button
                    v-for="m in list"
                    :key="m"
                    @click="toggleMajor(m)"
                    class="rounded-control border px-1.5 py-0.5 text-micro transition-colors"
                    :class="majorToneOf(m) || 'border-line text-ink-muted hover:border-line-strong'"
                    :title="majorLaneOf(m) ? '點一下移除' : `加入${laneLabel(majorTarget)}`"
                  >
                    {{ m }}
                  </button>
                </div>
              </div>
            </div>
          </section>

          <section class="rounded-card border border-line bg-surface p-5">
            <header>
              <h2 class="text-small font-semibold text-ink">評分權重</h2>
              <p class="mt-0.5 text-micro text-ink-muted">留空則沿用全域評分設定。總和須為 100%。</p>
            </header>
            <div class="mt-3 space-y-2">
              <div v-for="k in weightKeys" :key="k" class="flex items-center gap-2">
                <span class="w-20 shrink-0 text-micro text-ink-muted">{{ weightLabels[k] }}</span>
                <input
                  type="range" min="0" max="1" step="0.01"
                  v-model.number="profile.weights[k]"
                  class="flex-1 accent-brand"
                />
                <span class="w-10 text-right text-micro text-ink-muted">{{ Math.round((profile.weights[k] || 0) * 100) }}%</span>
              </div>
            </div>
            <div
              class="mt-3 flex items-center justify-between rounded-control px-3 py-2 text-micro font-semibold"
              :class="weightOk ? 'bg-surface-2 text-ink-muted' : 'bg-bad-soft text-bad-ink'"
            >
              <span>總和</span>
              <span>{{ Math.round(weightTotal * 100) }}%<template v-if="!weightOk"> — 必須為 100%</template></span>
            </div>
          </section>
        </div>

        <!-- Hard filters -->
        <section class="rounded-card border border-line bg-surface p-5">
          <header class="mb-3 flex items-start justify-between gap-3">
            <div>
              <h2 class="text-small font-semibold text-ink">硬性條件</h2>
              <p class="mt-0.5 text-micro leading-relaxed text-ink-muted">
                不符合就直接刷掉。每組至少要命中指定數量的字詞。條件越少越好——
                這裡設得太嚴會把整批人刷光，請用試算確認。
              </p>
            </div>
            <button
              @click="addFilterGroup"
              class="shrink-0 rounded-control border border-line px-2.5 py-1 text-micro font-semibold text-ink-muted hover:border-line-strong"
            >
              新增條件組
            </button>
          </header>
          <!-- Degree gate. Separate from the keyword groups because it reads the
               parsed education rows, not the resume text: "碩士" in a resume is
               usually a colleague's degree or a quoted job requirement. -->
          <label class="mb-3 flex flex-wrap items-center gap-2 rounded-control border border-line p-2">
            <span class="text-micro font-medium text-ink-muted">最低學歷</span>
            <select v-model="minEducation" class="field px-2 py-1 text-micro">
              <option v-for="opt in educationOptions" :key="opt.value" :value="opt.value">
                {{ opt.label }}
              </option>
            </select>
            <span class="text-micro text-ink-faint">
              {{ minEducation ? '學歷低於此門檻者直接刷掉（履歷無學歷資料者亦會被刷掉）' : '不限學歷' }}
            </span>
          </label>

          <!-- School gate. Tiers are global (a top school is a top school for
               any role), so this is a level picker rather than a name list. -->
          <label class="mb-3 flex flex-wrap items-center gap-2 rounded-control border border-line p-2">
            <span class="text-micro font-medium text-ink-muted">最低學校</span>
            <select v-model="minSchoolTier" class="field px-2 py-1 text-micro">
              <option v-for="opt in schoolOptions" :key="opt.value" :value="opt.value">
                {{ opt.label }}
              </option>
            </select>
            <span class="text-micro text-ink-faint">
              {{ schoolHint }}
            </span>
          </label>

          <p v-if="!filterGroups.length" class="text-micro text-ink-faint">未設定關鍵字條件組（學歷以外不再過濾）。</p>
          <div v-else class="space-y-2">
            <div v-for="(g, gi) in filterGroups" :key="gi" class="flex items-center gap-2 rounded-control border border-line p-2">
              <input v-model="g.name" placeholder="條件名稱" class="w-36 field px-2 py-1 text-micro" />
              <input
                :value="(g.skills || []).join('、')"
                @input="g.skills = splitList($event.target.value)"
                placeholder="關鍵字（用、分隔）"
                class="flex-1 field px-2 py-1 text-micro"
              />
              <span class="text-micro text-ink-muted">至少</span>
              <input v-model.number="g.min_matches" type="number" min="1" class="w-14 field px-2 py-1 text-right text-micro" />
              <button
                @click="filterGroups.splice(gi, 1)"
                class="field px-2 py-1 text-micro text-ink-muted hover:border-bad-line hover:text-bad-ink"
              >
                移除
              </button>
            </div>
          </div>
        </section>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  activateJobPosting,
  fetchJobPosting,
  fetchMajorCatalogue,
  previewJobProfile,
  regenerateJobProfile,
  saveJobProfile,
} from '../api'
import { ChevronDown } from 'lucide-vue-next'

const route = useRoute()
const jobId = Number(route.params.id)

const profile = ref(null)
const job = ref(null)
const sourceDocument = ref('')
const jobTitle = ref('')
const profileStatus = ref('none')
const errors = ref([])
const loading = ref(true)
const loadError = ref('')
const saving = ref(false)
const regenerating = ref(false)
const previewing = ref(false)
const preview = ref(null)
const savedMsg = ref('')
const dirty = ref(false)

const weightKeys = ['experience', 'engineering', 'semantic', 'education', 'skills']
const weightLabels = {
  experience: '領域深度',
  engineering: '能力面向',
  semantic: '語意匹配',
  education: '學歷',
  skills: '技能驗證',
}

// Keyword textareas are edited as "term:weight" lines, kept in a separate
// buffer so a half-typed line does not destroy the parsed map on every stroke.
const keywordText = ref({ 1: '', 2: '', 3: '' })

function syncKeywordText() {
  const kws = profile.value?.tier_keywords || {}
  for (const lvl of ['1', '2', '3']) {
    keywordText.value[lvl] = Object.entries(kws[lvl] || {})
      .map(([k, w]) => `${k}:${w}`)
      .join('\n')
  }
}

function onKeywordInput(lvl, text) {
  keywordText.value[lvl] = text
  const map = {}
  for (const line of text.split('\n')) {
    const trimmed = line.trim()
    if (!trimmed) continue
    const idx = trimmed.lastIndexOf(':')
    const term = (idx > 0 ? trimmed.slice(0, idx) : trimmed).trim()
    const weight = idx > 0 ? parseFloat(trimmed.slice(idx + 1)) : NaN
    if (!term) continue
    map[term] = Number.isFinite(weight) ? weight : Number(lvl) * 0.7
  }
  profile.value.tier_keywords[lvl] = map
}

function keywordCount(lvl) {
  return Object.keys(profile.value?.tier_keywords?.[lvl] || {}).length
}

function tierLabel(level) {
  return profile.value?.tiers?.find((t) => t.level === level)?.label || `Tier ${level}`
}

function splitList(text) {
  return text
    .split(/[、,，\n]/)
    .map((s) => s.trim())
    .filter(Boolean)
}

// --- Parsed JD, for review ---------------------------------------------------
// The generated standard is only trustworthy if the reviewer can see what the
// LLM actually read out of the document. Without this, "確認並啟用" asks someone
// to approve keywords with no way to check them against the source.

// Two JD shapes reach this page and both must read as Chinese, not JSON.
// `_JD_EXTRACT_PROMPT` emits flat fields (education: "", majors: [], languages:
// []), while job_requirement.json — the seeded AI role, and what embeddings.py
// scores against — nests them (education: {degree, preferred_majors},
// languages: {chinese: {listening, ...}}). Vue's {{ }} stringifies an object as
// JSON, so a nested job rendered its 學歷 / 語言 / 工作地點 as a raw blob.
// `asText` therefore formats *any* value structurally rather than per-field, so
// a JD key nobody anticipated still renders as text.

/** Chinese labels for the nested sub-keys the two schemas actually use. */
const FIELD_LABELS = {
  degree: '學歷',
  preferred_majors: '科系',
  years_required: '年資',
  address: '地址',
  industrial_park: '園區',
  remote_work: '遠端',
  required: '需求',
  timeframe: '期間',
  listening: '聽',
  speaking: '說',
  reading: '讀',
  writing: '寫',
  chinese: '中文',
  english: '英文',
  japanese: '日文',
  tools: '工具',
  skills: '技能',
  driver_license: '駕照',
  certifications: '證照',
}

/** Empty in the JSON sense: null/""/[]/{} — and false, which reads as "no". */
function isBlank(v) {
  if (v === null || v === undefined || v === '') return true
  if (Array.isArray(v)) return v.every(isBlank)
  if (typeof v === 'object') return Object.values(v).every(isBlank)
  return false
}

/**
 * Render any JSON value as readable Chinese.
 *
 * Objects become「鍵：值」pairs joined by「，」and recurse, so
 * {chinese: {reading: "精通"}} reads「中文：讀 精通」rather than a JSON blob.
 * Blank members are dropped — showing `industrial_park: null` tells a reviewer
 * nothing except that the parser has a field by that name.
 */
function asText(value, depth = 0) {
  if (isBlank(value)) return ''
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (typeof value !== 'object') return String(value)

  if (Array.isArray(value)) {
    return value.map((v) => asText(v, depth)).filter(Boolean).join('、')
  }

  const entries = []
  for (const [key, raw] of Object.entries(value)) {
    const text = asText(raw, depth + 1)
    if (text) entries.push([key, raw, text])
  }

  // When only one entry survives, the row's own heading already names it:
  // work_location with just an address is「新北市…」, not「地址：新北市…」.
  if (depth === 0 && entries.length === 1) return entries[0][2]

  return entries
    .map(([key, raw, text]) => {
      const label = FIELD_LABELS[key]
      if (!label) return text
      // Nested groups keep「：」; leaves inside a group use a space, so a language
      // reads「中文：聽 精通，說 精通」instead of stacking colons.
      return depth > 0 && typeof raw !== 'object' ? `${label} ${text}` : `${label}：${text}`
    })
    .join('，')
}

const basic = computed(() => basicRowsOf(job.value?.basic_conditions || {}))

function basicRowsOf(b) {
  return [
    ['職稱', b.job_title],
    ['職務屬性', b.employment_type],
    ['需求人數', b.headcount],
    ['部門', b.department],
    ['職務類別', b.job_categories],
    ['工作地點', b.work_location],
    ['出差', b.business_trip],
    ['管理責任', b.management_responsibility],
  ]
}

const basicRows = computed(() =>
  basic.value.map(([label, v]) => [label, asText(v)]).filter(([, v]) => v !== ''),
)

/**
 * Pull one sub-key out of a nested value, or take the value itself when the
 * schema is already flat.
 *
 * The nested schema packs 學歷 and 科系 into a single `education` object; they
 * are two rows here, and rendering the whole object under both would print the
 * majors twice under a 學歷 heading.
 */
function pick(value, key) {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return key in value ? value[key] : undefined
  }
  return key === undefined ? value : undefined
}

const requirementRows = computed(() => {
  const r = job.value?.requirements || {}
  const edu = r.education
  const exp = r.experience_years ?? r.experience
  return [
    // Flat (LLM) and nested (job_requirement.json) keys for the same idea. Only
    // one shape is ever present, so listing both keeps this a single row list.
    ['學歷', pick(edu, 'degree') ?? (typeof edu === 'object' ? undefined : edu)],
    ['科系', r.majors ?? pick(edu, 'preferred_majors')],
    ['年資', pick(exp, 'years_required') ?? (typeof exp === 'object' ? undefined : exp)],
    ['技能條件', r.skills ?? r.technical_foundation],
    ['核心能力', r.core_competencies],
    ['學習動機', r.learning_motivation],
    ['語言', r.languages],
    ['證照', r.certifications],
    ['其他', r.others ?? r.other_constraints],
  ]
    .map(([label, v]) => [label, asText(v)])
    .filter(([, v]) => v !== '')
})

const responsibilities = computed(() => job.value?.responsibilities || [])
const preferred = computed(() => job.value?.preferred_qualifications || [])

// Expanded by default: the parsed JD is the reference the reviewer checks when
// a keyword looks wrong.
const showParsed = ref(true)

// --- Majors ---------------------------------------------------------------
// tier1 = highly relevant, tier2 = related. Two lanes, so a click needs to know
// which one it targets; `majorTarget` is that choice.
const majorLanes = [
  { key: 'tier1_majors', label: '高度對口科系', short: '高度對口', tone: 'border-expert-line bg-expert-soft text-expert-ink' },
  { key: 'tier2_majors', label: '相關科系', short: '相關', tone: 'border-info-line bg-info-soft text-info-ink' },
]

const majorCatalogue = ref({})
const catalogueError = ref('')
const majorTarget = ref('tier1_majors')
const newMajor = ref({ tier1_majors: '', tier2_majors: '' })

function laneLabel(key, short = false) {
  const lane = majorLanes.find((l) => l.key === key) || majorLanes[0]
  return short ? lane.short : lane.label
}

/** Which lane a major currently sits in, or null. */
function majorLaneOf(name) {
  for (const lane of majorLanes) {
    if ((profile.value?.education?.[lane.key] || []).includes(name)) return lane.key
  }
  return null
}

function majorToneOf(name) {
  const key = majorLaneOf(name)
  return key ? majorLanes.find((l) => l.key === key).tone : null
}

function addMajor(laneKey, name) {
  const value = (name || '').trim()
  if (!value || !profile.value) return
  // A major belongs to exactly one lane: listing it in both would double-count
  // it and leave the two tiers contradicting each other.
  for (const lane of majorLanes) {
    const list = profile.value.education[lane.key] || []
    profile.value.education[lane.key] = list.filter((m) => m !== value)
  }
  profile.value.education[laneKey] = [value, ...(profile.value.education[laneKey] || [])]
}

function removeMajor(laneKey, name) {
  if (!profile.value) return
  profile.value.education[laneKey] = (profile.value.education[laneKey] || []).filter((m) => m !== name)
}

/** How many of a field's majors are already in the TARGET lane. */
function groupSelectedCount(list) {
  const chosen = profile.value?.education?.[majorTarget.value] || []
  return list.filter((m) => chosen.includes(m)).length
}

function groupFullyIn(list) {
  return list.length > 0 && groupSelectedCount(list) === list.length
}

/**
 * Add every major in a field to the target lane, or clear them if they are all
 * already there. Partial selections fill up rather than clearing, since the
 * visible label in that state is "全選" and it must do what it says.
 */
function toggleGroup(field, list) {
  if (!profile.value) return
  if (groupFullyIn(list)) {
    for (const m of list) removeMajor(majorTarget.value, m)
    return
  }
  // Preserve the catalogue's order for a bulk add: reusing addMajor would
  // unshift each one and leave the group reversed.
  const target = majorTarget.value
  const others = majorLanes.filter((l) => l.key !== target)
  for (const lane of others) {
    profile.value.education[lane.key] =
      (profile.value.education[lane.key] || []).filter((m) => !list.includes(m))
  }
  const existing = profile.value.education[target] || []
  const additions = list.filter((m) => !existing.includes(m))
  profile.value.education[target] = [...additions, ...existing]
}

/** Catalogue click: file into the target lane, or remove if already chosen. */
function toggleMajor(name) {
  const current = majorLaneOf(name)
  if (current) removeMajor(current, name)
  else addMajor(majorTarget.value, name)
}

// Value strings match the ladder in app/scoring/hard_filter.py; '' means no gate.
const educationOptions = [
  { value: '', label: '不限' },
  { value: 'high_school', label: '高中以上' },
  { value: 'associate', label: '專科以上' },
  { value: 'bachelor', label: '學士以上' },
  { value: 'master', label: '碩士以上' },
  { value: 'phd', label: '博士' },
]

// Tiers mirror app/scoring/education.py's global school ladder. "S" is not
// offered: it is the PhD premium, not a school rank.
const schoolOptions = [
  { value: '', label: '不限' },
  { value: 'C', label: '一般大學以上（C 級）' },
  { value: 'B', label: '中字輩以上（B 級）' },
  { value: 'A', label: '頂尖大學（A 級）' },
]

const schoolHints = {
  '': '不限學校',
  C: '一般國立大學、知名私立大學以上（如高雄大學、淡江、逢甲、輔仁）',
  B: '中央、中興、中正、中山、北科、師大等級以上',
  A: '台、清、交、成、政、台科，以及國外頂尖名校',
}

const minSchoolTier = computed({
  get() {
    return profile.value?.hard_filters?.min_school_tier || ''
  },
  set(v) {
    if (!profile.value) return
    if (!profile.value.hard_filters) profile.value.hard_filters = {}
    profile.value.hard_filters.min_school_tier = v
  },
})

const schoolHint = computed(() => schoolHints[minSchoolTier.value] || '')

const minEducation = computed({
  get() {
    return profile.value?.hard_filters?.min_education || ''
  },
  set(v) {
    if (!profile.value) return
    if (!profile.value.hard_filters) profile.value.hard_filters = {}
    profile.value.hard_filters.min_education = v
  },
})

const filterGroups = computed(() => {
  if (!profile.value) return []
  if (!profile.value.hard_filters) profile.value.hard_filters = {}
  if (!profile.value.hard_filters.must_have_groups) {
    profile.value.hard_filters.must_have_groups = []
  }
  return profile.value.hard_filters.must_have_groups
})

const weightTotal = computed(() =>
  weightKeys.reduce((sum, k) => sum + (profile.value?.weights?.[k] || 0), 0),
)
const weightOk = computed(() => Math.abs(weightTotal.value - 1) < 0.005 || weightTotal.value === 0)

const previewStats = computed(() => {
  const p = preview.value
  if (!p) return []
  return [
    { label: '最低分', value: p.score_min },
    { label: '平均', value: p.score_avg },
    { label: '最高分', value: p.score_max },
    { label: '硬性條件刷掉', value: `${p.rejected_by_hard_filter} 人` },
  ]
})

function addCompetency() {
  profile.value.competencies.push({
    key: `c${profile.value.competencies.length + 1}`,
    label: '',
    weight: 0.25,
    levels: { 1: [], 2: [], 3: [] },
  })
}

function addFilterGroup() {
  filterGroups.value.push({ name: '', skills: [], min_matches: 1 })
}

function applyProfile(p) {
  if (!p) {
    profile.value = null
    return
  }
  // Normalise the optional maps once here so every template binding can assume
  // they exist rather than guarding on each access.
  p.weights = p.weights && Object.keys(p.weights).length ? p.weights : {}
  for (const k of weightKeys) if (p.weights[k] == null) p.weights[k] = 0
  p.education = p.education || { matters: true, tier1_majors: [], tier2_majors: [] }
  p.hard_filters = p.hard_filters || {}
  if (p.hard_filters.min_education == null) p.hard_filters.min_education = ''
  if (p.hard_filters.min_school_tier == null) p.hard_filters.min_school_tier = ''
  p.tier_keywords = p.tier_keywords || {}
  p.competencies = p.competencies || []
  for (const c of p.competencies) c.levels = c.levels || {}
  profile.value = p
  syncKeywordText()
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const data = await fetchJobPosting(jobId)
    job.value = data.job || null
    sourceDocument.value = data.source_document || ''
    jobTitle.value = data.job?.basic_conditions?.job_title || data.title || '未命名職缺'
    profileStatus.value = data.profile_status
    errors.value = data.errors || []
    applyProfile(data.profile)
    dirty.value = false

    // Suggestions only: a failure here still leaves manual entry working, so
    // it must not fail the page load.
    try {
      majorCatalogue.value = (await fetchMajorCatalogue()).catalogue
    } catch (e) {
      catalogueError.value = e?.message || '讀取失敗'
      majorCatalogue.value = {}
    }
  } catch (e) {
    loadError.value = e?.response?.status === 404 ? '找不到這個職缺' : '無法連線到後端'
  } finally {
    loading.value = false
  }
}

async function doSave(activate) {
  saving.value = true
  savedMsg.value = ''
  try {
    const res = await saveJobProfile(jobId, profile.value, activate)
    errors.value = res.errors || []
    profileStatus.value = res.profile_status
    dirty.value = false
    if (activate) {
      await activateJobPosting(jobId)
      savedMsg.value = '已啟用。既有分數不會自動更新，請至背景工作執行重新評分。'
    } else {
      savedMsg.value = '草稿已儲存。'
    }
  } catch (e) {
    const d = e?.response?.data
    errors.value = d?.errors || [d?.detail || '儲存失敗']
  } finally {
    saving.value = false
  }
}

async function doRegenerate() {
  if (profile.value && !confirm('重新生成會覆蓋目前的評分標準，確定嗎？')) return
  regenerating.value = true
  savedMsg.value = ''
  try {
    const res = await regenerateJobProfile(jobId)
    applyProfile(res.profile)
    errors.value = res.errors || []
    profileStatus.value = res.profile_status
    dirty.value = false
  } catch (e) {
    errors.value = [e?.response?.data?.detail || '生成失敗']
  } finally {
    regenerating.value = false
  }
}

async function runPreview() {
  previewing.value = true
  try {
    // Send the in-editor profile, so a reviewer sees the effect of unsaved edits.
    preview.value = await previewJobProfile(jobId, { profile: profile.value, limit: 30 })
  } catch (e) {
    errors.value = [e?.response?.data?.error || e?.response?.data?.detail || '試算失敗']
  } finally {
    previewing.value = false
  }
}

watch(profile, () => { if (!loading.value) dirty.value = true }, { deep: true })

onMounted(load)
</script>
