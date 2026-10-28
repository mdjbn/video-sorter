<script setup lang="ts">
import { ref, watch } from 'vue'
import Icon from './Icon.vue'
import { api, type DirEntry } from '../api'

const props = defineProps<{ open: boolean; start?: string; title?: string }>()
const emit = defineEmits<{
  (e: 'update:open', v: boolean): void
  (e: 'pick', path: string): void
}>()

const cur = ref('')
const parent = ref<string | null>(null)
const dirs = ref<DirEntry[]>([])
const roots = ref<DirEntry[]>([])
const jump = ref('')
const loading = ref(false)
const err = ref('')

async function load(path?: string) {
  loading.value = true
  err.value = ''
  try {
    const r = await api.browse(path)
    cur.value = r.path
    parent.value = r.parent
    dirs.value = r.dirs
    jump.value = r.path
  } catch (e: any) {
    err.value = e?.message || '读取目录失败'
    dirs.value = []
  } finally {
    loading.value = false
  }
}

async function loadRoots() {
  if (roots.value.length) return
  try {
    roots.value = (await api.fsRoots()).roots
  } catch {
    roots.value = []
  }
}

watch(
  () => props.open,
  (v) => {
    if (!v) return
    loadRoots()
    load(props.start || '')
  },
)

function enter(path: string) {
  load(path)
}
function up() {
  if (parent.value) load(parent.value)
}
function go() {
  const p = jump.value.trim()
  if (p) load(p)
}
function choose() {
  if (!cur.value) return
  emit('pick', cur.value)
  emit('update:open', false)
}
function close() {
  emit('update:open', false)
}
</script>

<template>
  <div v-if="open" class="modal-mask show" @click.self="close">
    <div class="modal dirp">
      <h3>{{ title || '选择文件夹' }}</h3>
      <p>点文件夹进到下一级，最后点「选择这个文件夹」。</p>

      <div v-if="roots.length" class="dp-roots">
        <button v-for="r in roots" :key="r.path" class="chip" :title="r.path" @click="enter(r.path)">
          {{ r.name }}
        </button>
      </div>

      <div class="dp-bar">
        <button class="btn ghost sm" :disabled="!parent" title="上一级" @click="up">
          <Icon name="chevron-left" :size="14" />上一级
        </button>
        <input v-model="jump" class="field" spellcheck="false" placeholder="也可以直接输入路径" @keyup.enter="go" />
        <button class="btn ghost sm" @click="go">前往</button>
      </div>

      <div class="dp-list">
        <button v-for="d in dirs" :key="d.path" class="dp-row" :title="d.path" @click="enter(d.path)">
          <Icon name="folder" :size="15" />
          <span class="nm">{{ d.name }}</span>
          <Icon name="chevron-right" :size="14" />
        </button>
        <div v-if="loading" class="dp-hint">读取中…</div>
        <div v-else-if="err" class="dp-hint err">{{ err }}</div>
        <div v-else-if="!dirs.length" class="dp-hint">这个文件夹下没有子文件夹</div>
      </div>

      <div class="dp-cur" :title="cur">当前：<b>{{ cur || '—' }}</b></div>
      <div class="modal-actions">
        <button class="btn ghost" @click="close">取消</button>
        <button class="btn primary" :disabled="!cur" @click="choose">
          <Icon name="check" :size="15" />选择这个文件夹
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.dirp {
  max-width: 560px;
}
.dp-roots {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 10px 0 0;
}
.dp-bar {
  display: flex;
  gap: 8px;
  margin: 10px 0;
}
.dp-bar .field {
  flex: 1;
  min-width: 0;
}
.dp-list {
  max-height: 300px;
  overflow: auto;
  border: 1px solid var(--line, rgba(140, 155, 180, 0.22));
  border-radius: 10px;
  padding: 4px;
}
.dp-row {
  display: flex;
  align-items: center;
  gap: 9px;
  width: 100%;
  padding: 8px 10px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: inherit;
  font-size: 13px;
  text-align: left;
  cursor: pointer;
}
.dp-row:hover {
  background: var(--hover, rgba(140, 155, 180, 0.14));
}
.dp-row .nm {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dp-hint {
  padding: 14px 10px;
  font-size: 12.5px;
  color: var(--muted-2, #8d98a8);
  text-align: center;
}
.dp-hint.err {
  color: var(--danger, #f2705e);
}
.dp-cur {
  margin-top: 10px;
  font-size: 11.5px;
  color: var(--muted-2, #8d98a8);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dp-cur b {
  color: var(--muted, #b6c0cf);
  font-weight: 600;
}
</style>
