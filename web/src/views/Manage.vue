<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import Icon from '../components/Icon.vue'
import { api, fmtDur, fmtSize, fmtTime, waitTask, type HistoryItem, type PlanItem, type Source, type Stats, type Tag, type Video } from '../api'
import { toast } from '../toast'
import { nextThemeMode, setThemeMode, themeMode, THEME_LABEL } from '../theme'
import '../styles/manage.css'

const props = defineProps<{ user?: { username: string } | null }>()
const router = useRouter()

type View = 'overview' | 'library' | 'tags' | 'organize' | 'history' | 'account' | 'about'
const view = ref<View>('overview')
const navOpen = ref(false)   // 窄屏抽屉导航
const VIEW_TITLE: Record<View, string> = {
  overview: '概览', library: '视频库', tags: '标签管理', organize: '整理',
  history: '播放历史', account: '登录管理', about: '关于项目',
}
const views: { id: View; label: string; icon: string; group?: string }[] = [
  { id: 'overview', label: '概览', icon: 'grid' },
  { id: 'library', label: '视频库', icon: 'film' },
  { id: 'tags', label: '标签管理', icon: 'tag' },
  { id: 'organize', label: '整理', icon: 'move' },
  { id: 'history', label: '播放历史', icon: 'clock', group: '记录与设置' },
  { id: 'account', label: '登录管理', icon: 'shield' },
  { id: 'about', label: '关于项目', icon: 'info' },
]

const tags = ref<Tag[]>([])
const stats = ref<Stats | null>(null)
const sources = ref<Source[]>([])
const records = ref<any[]>([])
const history = ref<HistoryItem[]>([])
const info = ref<any>(null)
const sessions = ref<any[]>([])
const busy = ref(false)

const counts = reactive({ lib: 0, tags: 0, org: 0, hist: 0 })
const username = computed(() => props.user?.username || 'admin')
const initial = computed(() => (username.value[0] || 'A').toUpperCase())

async function loadTags() {
  tags.value = (await api.tags()).tags
  counts.tags = tags.value.length
}
async function loadStats() {
  stats.value = await api.stats()
  counts.org = stats.value.tagged_pending || 0
}
async function loadSources() { sources.value = (await api.sources()).sources }
async function loadRecords() {
  try { records.value = (await api.records()).items } catch { records.value = [] }
}
async function loadHistory() {
  try { history.value = (await api.history(200)).items } catch { history.value = [] }
  counts.hist = history.value.length
}
async function loadInfo() {
  try { info.value = await api.info() } catch { info.value = null }
}
async function loadSessions() {
  try { sessions.value = (await api.sessions()).sessions } catch { sessions.value = [] }
}

function go(v: View) {
  navOpen.value = false
  view.value = v
  if (v === 'library') loadLibrary()
  if (v === 'organize') loadPlan()
  if (v === 'history') loadHistory()
  if (v === 'account') loadSessions()
  if (v === 'about') loadInfo()
}

/* ---------------- 扫描 ---------------- */
const scan = reactive({ running: false, percent: 0, text: '' })
async function runScan() {
  if (scan.running) return
  scan.running = true; scan.percent = 0; scan.text = '准备扫描…'
  try {
    const { task_id } = await api.scan()
    const task = await waitTask(task_id, (t) => {
      scan.percent = t.percent || 0
      scan.text = t.message || `扫描中 ${t.done}/${t.total}`
    })
    const r: any = task.result || {}
    scan.text = `扫描完成：新增 ${r.added ?? 0}，更新 ${r.updated ?? 0}，丢失 ${r.missing ?? 0}`
    toast(`扫描完成，新增 ${r.added ?? 0} 个视频`)
    await Promise.all([loadStats(), loadSources(), loadTags()])
    if (view.value === 'library') await loadLibrary()
    if (view.value === 'organize') await loadPlan()
  } catch (e: any) {
    toast(e?.message || '扫描失败', true)
  } finally {
    scan.running = false
    setTimeout(() => { scan.percent = 0; scan.text = '' }, 6000)
  }
}
const newSource = ref('')
async function addSource() {
  const p = newSource.value.trim()
  if (!p) return
  try {
    await api.addSource(p)
    newSource.value = ''
    await Promise.all([loadSources(), loadStats()])
    toast('已添加源文件夹')
  } catch (e: any) { toast(e?.message || '添加失败', true) }
}
async function removeSource(id: number) {
  try {
    await api.removeSource(id)
    await Promise.all([loadSources(), loadStats()])
    toast('已移除')
  } catch (e: any) { toast(e?.message || '移除失败', true) }
}

/* ---------------- 视频库 ---------------- */
const lib = reactive({ status: 'all', tags: new Set<number>(), q: '', mode: 'grid' as 'grid' | 'list' })
const videos = ref<Video[]>([])
const sel = reactive(new Set<number>())
// 视频库分两组展示：还在源文件夹里的 / 已按标签整理到标签文件夹的
const sourceVideos = computed(() => videos.value.filter((v) => !v.organized))
const organizedVideos = computed(() => videos.value.filter((v) => v.organized))
const libGroups = computed(() => [
  { k: 'source', title: '源文件夹', icon: 'folder', desc: '还没整理，文件仍在源文件夹里', items: sourceVideos.value },
  { k: 'organized', title: '标签文件夹', icon: 'tag', desc: '已整理，文件已移动到标签对应的文件夹', items: organizedVideos.value },
])
const libLoading = ref(false)

const libChips = computed<any[]>(() => {
  const base = [
    { k: 'all', label: '全部' },
    { k: 'untagged', label: '未打标签' },
    { k: 'tagged', label: '待整理' },
    { k: 'organized', label: '已整理' },
  ]
  return [...base.map((b) => ({ ...b, v: b.k, on: lib.status === b.k && lib.tags.size === 0 })),
    ...tags.value.map((t) => ({ k: `tag:${t.id}`, label: t.name, v: t.name, on: lib.tags.has(t.id), color: t.color }))]
})
function chipClick(c: any) {
  if (c.k.startsWith('tag:')) {
    // 标签多选：点一次加入、再点移除（取并集），状态筛选清空
    const id = Number(c.k.slice(4))
    if (lib.tags.has(id)) lib.tags.delete(id)
    else lib.tags.add(id)
    lib.status = 'all'
  } else {
    lib.status = c.k
    lib.tags.clear()
  }
  loadLibrary()
}
async function loadLibrary() {
  libLoading.value = true
  try {
    const r = await api.videos({
      status: lib.status,
      tags: lib.tags.size ? [...lib.tags].join(',') : undefined,
      q: lib.q.trim() || undefined,
      sort: 'added', order: 'desc', limit: 600,
    })
    videos.value = r.items
    counts.lib = ((r.counts as any)?.total) || r.items.length
  } catch (e: any) { toast(e?.message || '加载失败', true) }
  finally { libLoading.value = false }
}
let libTimer: any = null
watch(() => lib.q, () => { clearTimeout(libTimer); libTimer = setTimeout(loadLibrary, 260) })
function toggleSel(id: number) { sel.has(id) ? sel.delete(id) : sel.add(id) }
async function bulkTag(tagId: number) {
  if (!sel.size) return
  busy.value = true
  try {
    await Promise.all([...sel].map((id) => api.setTag(id, tagId)))
    toast(`已为 ${sel.size} 个视频打标签`)
    sel.clear()
    await Promise.all([loadLibrary(), loadStats(), loadTags()])
  } catch (e: any) { toast(e?.message || '操作失败', true) }
  finally { busy.value = false }
}
function openVideo(v: Video) { router.push({ path: '/', query: { v: String(v.id) } }) }

/* ---------------- 上传（与手机端共用同一个上传目录） ---------------- */
type UploadItem = { name: string; pct: number; state: 'run' | 'ok' | 'err'; msg?: string }
const uploads = ref<UploadItem[]>([])
const fileInput = ref<HTMLInputElement | null>(null)
function pickFiles() { fileInput.value?.click() }
function clearUploads() { uploads.value = uploads.value.filter((u) => u.state === 'run') }
function errText(text: string): string {
  try { const j = JSON.parse(text); return j.detail || j.error || '上传失败' } catch { return '上传失败' }
}
function uploadOne(f: File): Promise<void> {
  return new Promise((resolve) => {
    const item: UploadItem = { name: f.name, pct: 0, state: 'run' }
    uploads.value.unshift(item)
    const fd = new FormData()
    fd.append('file', f)
    const xhr = new XMLHttpRequest()
    xhr.open('POST', '/api/upload')
    xhr.withCredentials = true
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) item.pct = Math.round((e.loaded / e.total) * 100) }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) { item.pct = 100; item.state = 'ok' }
      else { item.state = 'err'; item.msg = errText(xhr.responseText) }
      resolve()
    }
    xhr.onerror = () => { item.state = 'err'; item.msg = '网络错误'; resolve() }
    xhr.send(fd)
  })
}
async function onFiles(ev: Event) {
  const input = ev.target as HTMLInputElement
  const files = Array.from(input.files || [])
  input.value = ''
  if (!files.length) return
  try {
    for (const f of files) await uploadOne(f)
    const ok = uploads.value.filter((u) => u.state === 'ok').length
    toast(`上传完成 ${ok} 个，正在刷新视频库`)
    await Promise.all([loadLibrary(), loadStats()])
  } catch (e: any) { toast(e?.message || '上传失败', true) }
}

/* ---------------- 删除视频（单个 / 批量） ---------------- */
const delVideo = reactive({ show: false, ids: [] as number[], names: [] as string[] })
const delFile = ref(false)
function openDelVideo(ids: number[], names: string[]) {
  delVideo.ids = ids
  delVideo.names = names
  delFile.value = false
  delVideo.show = true
}
async function doDelVideo() {
  const ids = [...delVideo.ids]
  if (!ids.length) return
  delVideo.show = false
  busy.value = true
  try {
    const withFile = delFile.value
    for (const id of ids) await api.deleteVideo(id, withFile)
    sel.clear()
    toast(withFile ? `已删除 ${ids.length} 个视频（含文件）` : `已删除 ${ids.length} 条记录`)
    await Promise.all([loadLibrary(), loadStats(), loadTags()])
  } catch (e: any) { toast(e?.message || '删除失败', true) }
  finally { busy.value = false }
}

/* ---------------- 标签管理 ---------------- */
const tagModal = reactive({ show: false, id: 0, name: '', color: '#35d18a', dir: '', saving: false })
const TAG_COLORS = [
  '#f4a259', '#ef5b7b', '#4cc9f0', '#9b8cff',
  '#8d98a8', '#35d18a', '#f2c14e', '#ef7d4f',
  '#e76f51', '#2a9d8f', '#457b9d', '#b5179e',
]

/* ---------- 标签行内编辑（不弹卡片） ---------- */
interface TagDraft { name: string; color: string; dir_path: string }
const tagDrafts = reactive<Record<number, TagDraft>>({})
const tagState = reactive<Record<number, 'idle' | 'saving' | 'saved' | 'err'>>({})
const colorPop = reactive<{ id: number | null }>({ id: null })
const saveTimers: Record<number, ReturnType<typeof setTimeout>> = {}

function draftOf(t: Tag): TagDraft {
  if (!tagDrafts[t.id]) {
    tagDrafts[t.id] = { name: t.name, color: t.color || TAG_COLORS[0], dir_path: t.dir_path || '' }
  }
  return tagDrafts[t.id]
}
function normalizeHex(v: string): string {
  let s = (v || '').trim()
  if (!s) return ''
  if (!s.startsWith('#')) s = '#' + s
  if (/^#[0-9a-fA-F]{3}$/.test(s)) s = '#' + s.slice(1).split('').map((c) => c + c).join('')
  return /^#[0-9a-fA-F]{6}$/.test(s) ? s.toLowerCase() : ''
}
function queueSave(id: number) {
  clearTimeout(saveTimers[id])
  tagState[id] = 'idle'
  saveTimers[id] = setTimeout(() => void saveTagInline(id), 500)
}
async function saveTagInline(id: number) {
  const d = tagDrafts[id]
  if (!d) return
  const name = d.name.trim()
  if (!name) { tagState[id] = 'err'; return }
  tagState[id] = 'saving'
  try {
    await api.updateTag(id, { name, color: d.color, dir_path: d.dir_path.trim() })
    tagState[id] = 'saved'
    await loadTags()
    setTimeout(() => { if (tagState[id] === 'saved') tagState[id] = 'idle' }, 1600)
  } catch (e) {
    tagState[id] = 'err'
    toast((e as Error).message || '保存失败', true)
  }
}
function toggleColorPop(id: number) { colorPop.id = colorPop.id === id ? null : id }
function setColor(id: number, c: string) {
  const t = tags.value.find((x) => x.id === id)
  if (!t) return
  draftOf(t).color = c
  void saveTagInline(id)
  colorPop.id = null
}
function onColorPicker(id: number, e: Event) {
  const t = tags.value.find((x) => x.id === id)
  if (!t) return
  draftOf(t).color = (e.target as HTMLInputElement).value
  queueSave(id)
}
function onHexInput(id: number, e: Event) {
  const t = tags.value.find((x) => x.id === id)
  if (!t) return
  draftOf(t).color = (e.target as HTMLInputElement).value
  queueSave(id)
}
function closeColorPop(e: MouseEvent) {
  const el = e.target as HTMLElement
  if (el.closest('.color-pop') || el.closest('.dot-btn')) return
  colorPop.id = null
}
function openTag(t?: Tag) {
  tagModal.id = t?.id || 0
  tagModal.name = t?.name || ''
  tagModal.color = t?.color || TAG_COLORS[0]
  tagModal.dir = t?.dir_path || ''
  tagModal.show = true
}
async function saveTag() {
  if (!tagModal.name.trim()) return toast('请填写标签名称', true)
  tagModal.saving = true
  try {
    if (tagModal.id) await api.updateTag(tagModal.id, { name: tagModal.name.trim(), color: tagModal.color, dir_path: tagModal.dir.trim() })
    else await api.createTag({ name: tagModal.name.trim(), color: tagModal.color, dir_path: tagModal.dir.trim() })
    tagModal.show = false
    await Promise.all([loadTags(), loadStats()])
    toast(tagModal.id ? '已保存标签' : '已创建标签')
  } catch (e: any) { toast(e?.message || '保存失败', true) }
  finally { tagModal.saving = false }
}
const delTag = reactive({ show: false, tag: null as Tag | null })
async function doDelTag() {
  if (!delTag.tag) return
  try {
    await api.deleteTag(delTag.tag.id)
    delTag.show = false
    await Promise.all([loadTags(), loadStats()])
    toast('已删除标签，相关视频已回落为未打标签')
  } catch (e: any) { toast(e?.message || '删除失败', true) }
}

/* ---------------- 整理 ---------------- */
const plan = ref<{ items: PlanItem[]; total: number; total_bytes: number; skipped: number } | null>(null)
const planLoading = ref(false)
const selTags = reactive(new Set<number>())
const orgInit = ref(false)
const orgRun = reactive({ running: false, percent: 0, text: '' })

const planGroups = computed(() => {
  const items = plan.value?.items || []
  const map = new Map<number, { tag_id: number; name: string; color: string; dir: string; items: PlanItem[] }>()
  for (const it of items) {
    const g = map.get(it.tag_id) || { tag_id: it.tag_id, name: it.tag_name, color: it.tag_color, dir: it.dir, items: [] }
    g.items.push(it); map.set(it.tag_id, g)
  }
  return [...map.values()]
})
const selItems = computed(() => (plan.value?.items || []).filter((i) => selTags.has(i.tag_id)))
const selBytes = computed(() => selItems.value.reduce((a, b) => a + (b.size || 0), 0))
const planDirs = computed(() => new Set(selItems.value.map((i) => i.dir)).size)

async function loadPlan() {
  planLoading.value = true
  try {
    plan.value = await api.preview()
    if (!orgInit.value) {
      selTags.clear()
      for (const g of planGroups.value) selTags.add(g.tag_id)
      orgInit.value = true
    }
    // 已不存在的分组自动取消勾选
    for (const id of [...selTags]) if (!planGroups.value.some((g) => g.tag_id === id)) selTags.delete(id)
  } catch (e: any) { toast(e?.message || '预览失败', true) }
  finally { planLoading.value = false }
}
function toggleTag(id: number) { selTags.has(id) ? selTags.delete(id) : selTags.add(id) }
function selectAll(b: boolean) {
  selTags.clear()
  if (b) for (const g of planGroups.value) selTags.add(g.tag_id)
  orgInit.value = true
}
async function runOrganize() {
  if (!selTags.size || orgRun.running) return
  orgRun.running = true; orgRun.percent = 0; orgRun.text = '准备移动…'
  try {
    const r: any = await api.execute({ tag_ids: [...selTags] })
    const task = await waitTask(r.task_id, (t) => {
      orgRun.percent = t.percent || 0
      orgRun.text = t.message || '正在移动…'
    })
    const res: any = task.result || {}
    orgRun.text = `完成：移动 ${res.moved ?? 0} 个，失败 ${res.failed?.length ?? 0} 个`
    toast(`整理完成，移动 ${res.moved ?? 0} 个视频`)
    orgInit.value = false
    await Promise.all([loadPlan(), loadStats(), loadRecords(), loadTags()])
    if (view.value === 'library') await loadLibrary()
  } catch (e: any) { toast(e?.message || '整理失败', true) }
  finally {
    orgRun.running = false
    setTimeout(() => { orgRun.percent = 0; orgRun.text = '' }, 6000)
  }
}
async function undo(batchId: string) {
  try {
    await api.undo(batchId)
    toast('已撤销这批整理')
    await Promise.all([loadPlan(), loadStats(), loadRecords(), loadTags()])
  } catch (e: any) { toast(e?.message || '撤销失败', true) }
}

/* ---------------- 历史 ---------------- */
async function delHist(videoId: number) {
  try {
    await api.deleteHistory(videoId)
    await loadHistory()
  } catch (e: any) { toast(e?.message || '删除失败', true) }
}
async function clearHist() {
  try { await api.clearHistory(); await loadHistory(); toast('已清空播放历史') }
  catch (e: any) { toast(e?.message || '清空失败', true) }
}
function histPct(h: any) { return h.duration ? Math.min(100, Math.round((h.position / h.duration) * 100)) : 0 }

/* ---------------- 账号 ---------------- */
const acc = reactive({ username: '', oldPass: '', newPass: '', newPass2: '', showPass: false })
const accSaving = ref(false)
async function savePassword() {
  if (!acc.oldPass || !acc.newPass) return toast('请填写当前密码与新密码', true)
  if (acc.newPass.length < 6) return toast('新密码至少 6 位', true)
  if (acc.newPass !== acc.newPass2) return toast('两次输入的新密码不一致', true)
  accSaving.value = true
  try {
    await api.changePassword(acc.oldPass, acc.newPass)
    acc.oldPass = acc.newPass = acc.newPass2 = ''
    toast('密码已修改，其他设备的登录已失效')
    await loadSessions()
  } catch (e: any) { toast(e?.message || '修改失败', true) }
  finally { accSaving.value = false }
}
async function saveUsername() {
  const n = acc.username.trim()
  if (!n) return toast('请输入用户名', true)
  try {
    await api.changeUsername(n)
    toast('用户名已修改')
    await loadSessions()
  } catch (e: any) { toast(e?.message || '修改失败', true) }
}
async function revokeAll() {
  try { await api.revokeAll(); await loadSessions(); toast('已退出全部设备') }
  catch (e: any) { toast(e?.message || '操作失败', true) }
}
const logoutModal = ref(false)
const appDl = reactive({
  show: false,
  loading: false,
  apps: [] as { name: string; abi: string; version: string; size: number; url: string }[],
  releases: 'https://github.com/mdjbn/video-sorter/releases/latest',
  version: '',
})
async function openAppDl() {
  appDl.show = true
  if (appDl.apps.length) return
  appDl.loading = true
  try {
    const r = await api.apkList()
    appDl.apps = r.apps
    appDl.releases = r.releases
    appDl.version = r.version
  } catch {
    /* 拿不到列表就只显示 GitHub 入口 */
  } finally {
    appDl.loading = false
  }
}
async function doLogout() {
  try { await api.logout() } catch {}
  location.reload()
}

function cycleTheme() { setThemeMode(nextThemeMode()) }
const themeTitle = computed(() => `切换主题 · 当前：${THEME_LABEL[themeMode.value]}`)

function onKeydown(e: KeyboardEvent) {
  if (e.key !== 'Escape') return
  // 有弹层时先让弹层处理，这里不跳转
  if (document.querySelector('.modal-mask.show')) return
  router.push('/')
}

onMounted(async () => {
  acc.username = username.value
  window.addEventListener('keydown', onKeydown)
  window.addEventListener('click', closeColorPop)
  window.addEventListener('resize', onResize)
  await Promise.all([loadTags(), loadStats(), loadSources(), loadRecords()])
  counts.lib = stats.value?.total || 0
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  window.removeEventListener('click', closeColorPop)
  window.removeEventListener('resize', onResize)
})
function onResize() {
  if (window.innerWidth > 820) navOpen.value = false
}
</script>

<template>
  <div class="m-app">
    <div v-if="navOpen" class="nav-mask" @click="navOpen = false" />
    <aside class="m-side" :class="{ open: navOpen }">
      <button class="back-side" @click="router.push('/')">
        <Icon name="chevron-left" :size="16" /><span>返回播放页</span>
      </button>
      <div class="m-nav">
        <template v-for="(v, i) in views" :key="v.id">
          <div v-if="v.group && (i === 0 || views[i - 1].group !== v.group)" class="nav-g">{{ v.group }}</div>
          <button class="nav-item" :class="{ on: view === v.id }" @click="go(v.id)">
            <Icon :name="v.icon" :size="17" /><span>{{ v.label }}</span>
            <i v-if="v.id === 'library'" class="cnt">{{ counts.lib }}</i>
            <i v-else-if="v.id === 'tags'" class="cnt">{{ counts.tags }}</i>
            <i v-else-if="v.id === 'organize' && counts.org" class="cnt">{{ counts.org }}</i>
            <i v-else-if="v.id === 'history' && counts.hist" class="cnt">{{ counts.hist }}</i>
          </button>
        </template>
      </div>
      <div class="m-side-foot">
        <button class="user-row" @click="go('account')">
          <span class="avatar">{{ initial }}</span>
          <span><span class="user-nm">{{ username }}</span><br /><span class="user-sub">单人使用</span></span>
          <span class="logout-mini" title="退出登录" @click.stop="logoutModal = true"><Icon name="logout" :size="15" /></span>
        </button>
      </div>
    </aside>

    <main class="m-main">
      <div class="m-top">
        <button class="nav-toggle" :class="{ open: navOpen }" aria-label="菜单" @click="navOpen = !navOpen">
          <Icon :name="navOpen ? 'close' : 'menu'" :size="18" />
        </button>
        <div class="m-crumb">视频整理 <span style="opacity:.4">/</span> <b>{{ VIEW_TITLE[view] }}</b></div>
        <div class="sp" />
        <button id="btnAppDl" class="btn primary top-cta" title="下载手机 App" @click="openAppDl">
          <Icon name="download" :size="15" /><span class="lbl-long">下载手机 App</span><span class="lbl-short">下载 App</span>
        </button>
        <button id="btnTheme" class="icon-btn" :title="themeTitle" @click="cycleTheme"><Icon :name="themeMode === 'auto' ? 'auto' : themeMode === 'light' ? 'sun' : 'moon'" :size="17" /></button>
      </div>

      <div class="m-scroll">
        <!-- ================= 概览 ================= -->
        <template v-if="view === 'overview'">
          <div class="m-head">
            <div>
              <div class="m-title">概览</div>
              <div class="m-desc">扫描源文件夹与标签文件夹、给视频打标签，然后一键把带标签的视频移动到对应文件夹。源文件夹的新增/移除在「视频库」页。</div>
            </div>
            <div class="sp" />
            <button class="btn primary" :disabled="scan.running" @click="runScan">
              <Icon name="refresh" :size="15" />{{ scan.running ? '扫描中…' : '扫描全部' }}
            </button>
          </div>

          <div class="ov-top">
            <!-- 四个统计卡片：2×2 -->
            <div class="stats">
              <div class="stat" style="--c:rgba(53,209,138,.18)">
                <div class="k">视频总数</div>
                <div class="v">{{ stats?.total ?? 0 }} <small>个</small></div>
                <div class="d">占用 {{ fmtSize(stats?.bytes ?? 0) }}</div>
              </div>
              <div class="stat" style="--c:rgba(244,162,89,.18)">
                <div class="k">待整理</div>
                <div class="v">{{ stats?.tagged_pending ?? 0 }} <small>个</small></div>
                <div class="d">已打标签、还没移动</div>
              </div>
              <div class="stat" style="--c:rgba(155,140,255,.16)">
                <div class="k">已整理</div>
                <div class="v">{{ stats?.organized ?? 0 }} <small>个</small></div>
                <div class="d">已移动到标签文件夹</div>
              </div>
              <div class="stat" style="--c:rgba(76,201,240,.16)">
                <div class="k">未打标签</div>
                <div class="v">{{ stats?.untagged ?? 0 }} <small>个</small></div>
                <div class="d">最近扫描 {{ stats?.last_scan_at ? fmtTime(stats.last_scan_at) : '尚未扫描' }}</div>
              </div>
            </div>

            <!-- 标签分布：固定尺寸，与统计卡同一排 -->
            <div class="card dist-card">
              <div class="card-head"><h2>标签分布</h2><div class="sp" /><button class="btn ghost sm" @click="go('tags')">管理标签</button></div>
              <div class="card-body">
                <div v-for="t in stats?.tags || []" :key="t.id" class="dist-row">
                  <span class="dot" :style="{ background: t.color }" />
                  <span class="nm">{{ t.name }}</span>
                  <span class="dist-bar"><i :style="{ width: ((t.count || 0) / Math.max(1, stats?.total || 1)) * 100 + '%', background: t.color }" /></span>
                  <span class="ct">{{ t.count ?? 0 }}</span>
                </div>
                <div v-if="!(stats?.tags || []).length" class="empty">暂无标签</div>
              </div>
            </div>
          </div>

          <div class="card" style="margin-top:14px">
            <div class="card-head"><h2>最近整理</h2><div class="sp" /><button class="btn ghost sm" @click="go('organize')">整理页</button></div>
            <div class="card-body">
              <div v-for="r in records.slice(0, 5)" :key="r.id" class="rec">
                <span class="dot" style="background:var(--accent)" />
                <div class="rt">
                  <b>{{ fmtTime(r.created_at) }} · 移动 {{ r.files ?? r.count ?? 0 }} 个</b>
                  <span>{{ (r.dirs || []).join(' / ') || r.note || '—' }}</span>
                </div>
                <button v-if="!r.undone" class="btn ghost sm" @click="undo(r.id)">撤销</button>
                <span v-else class="badge">已撤销</span>
              </div>
              <div v-if="!records.length" class="empty">还没有整理记录。打上标签后在整理页执行一次。</div>
            </div>
          </div>
        </template>

        <!-- ================= 视频库 ================= -->
        <template v-else-if="view === 'library'">
          <div class="m-head">
            <div>
              <div class="m-title">视频库</div>
              <div class="m-desc">点卡片进入播放页；勾选后可批量打标签。</div>
            </div>
            <div class="sp" />
            <input ref="fileInput" type="file" accept="video/*" multiple hidden @change="onFiles" />
            <button class="btn primary" @click="pickFiles"><Icon name="upload" :size="15" />上传视频</button>
            <button class="btn ghost" :disabled="scan.running" @click="runScan">
              <Icon name="refresh" :size="15" />{{ scan.running ? '扫描中…' : '扫描' }}
            </button>
          </div>
          <div class="lib-head">
            <label class="search"><Icon name="search" :size="15" /><input v-model="lib.q" placeholder="搜索文件名" spellcheck="false" /></label>
            <div class="chips">
              <button v-for="c in libChips" :key="c.k" class="chip" :class="{ on: c.on }" @click="chipClick(c)">
                <span v-if="c.color" class="dot" :style="{ background: c.color }" />{{ c.label }}
              </button>
            </div>
            <div class="sp" style="flex:1" />
            <div class="seg">
              <button :class="{ on: lib.mode === 'grid' }" @click="lib.mode = 'grid'">网格</button>
              <button :class="{ on: lib.mode === 'list' }" @click="lib.mode = 'list'">列表</button>
            </div>
          </div>
          <div v-if="uploads.length" class="upl">
            <div class="upl-head">
              <Icon name="upload" :size="14" />
              <b>上传到服务器</b>
              <span>文件会存到「源文件夹 → 上传目录」，手机端与网页端共用同一个目录</span>
              <div class="sp" />
              <button class="btn ghost sm" @click="clearUploads">清空</button>
            </div>
            <div v-for="(u, i) in uploads" :key="i" class="upl-row">
              <span class="nm">{{ u.name }}</span>
              <span class="bar"><i :style="{ width: u.pct + '%' }" :class="{ err: u.state === 'err' }" /></span>
              <span class="st" :class="u.state">{{ u.state === 'ok' ? '完成' : u.state === 'err' ? (u.msg || '失败') : u.pct + '%' }}</span>
            </div>
          </div>
          <div class="card" style="margin-bottom:14px">
              <div class="card-head">
                <h2>源文件夹</h2><div class="sp" /><span class="badge">{{ sources.length }} 个</span>
                <button class="btn ghost sm" :disabled="scan.running" @click="runScan">
                  <Icon name="refresh" :size="14" />{{ scan.running ? '扫描中…' : '扫描' }}
                </button>
              </div>
              <div class="card-body">
                <div v-for="s in sources" :key="s.id" class="src-row">
                  <Icon :name="s.kind === 'upload' ? 'upload' : 'folder'" :size="17" :style="{ color: s.kind === 'upload' ? 'var(--accent)' : 'var(--muted-2)' }" />
                  <div class="src-path">
                    <div class="p">
                      {{ s.path }}
                      <span v-if="s.kind === 'upload'" class="up-badge">上传目录</span>
                    </div>
                    <div class="s">
                      {{ s.count ?? 0 }} 个视频 · 上次扫描 {{ s.last_scan_at ? fmtTime(s.last_scan_at) : '从未' }}
                      <template v-if="s.kind === 'upload'"> · 手机/网页上传都存到这里，可改路径不可删除</template>
                    </div>
                  </div>
                  <button v-if="s.deletable !== false" class="icon-act dg" title="移除" @click="removeSource(s.id)"><Icon name="close" :size="15" /></button>
                </div>
                <div v-if="!sources.length" class="empty">还没有源文件夹，添加一个包含视频的目录。</div>
                <div style="display:flex;gap:8px;margin-top:12px">
                  <input v-model="newSource" class="field" placeholder="/volume1/videos/未整理" spellcheck="false" @keyup.enter="addSource" />
                  <button class="btn" @click="addSource">添加</button>
                </div>
                <div class="m-desc" style="font-size:11.5px;margin-top:10px">
                  扫描会同时遍历上面的源文件夹，以及「标签管理」里每个标签的目标文件夹（整理过的视频就存放在那里）。
                </div>
                <div v-if="scan.running || scan.percent > 0" class="scanbar">
                  <div class="track"><i :style="{ width: scan.percent + '%' }" /></div>
                  <span style="font-size:11.5px;color:var(--muted-2);min-width:120px">{{ scan.text }}</span>
                </div>
              </div>
            </div>
          <div v-for="g in libGroups" :key="g.k" class="lib-group">
            <div class="lib-group-head">
              <span class="ico"><Icon :name="g.icon" :size="14" /></span>
              <b>{{ g.title }}</b>
              <span class="cnt">{{ g.items.length }}</span>
              <span class="sub">{{ g.desc }}</span>
            </div>
            <div v-if="g.items.length" class="grid" :class="{ 'as-list': lib.mode === 'list' }">
              <div v-for="v in g.items" :key="v.id" class="vcard" :class="{ sel: sel.has(v.id) }" @click="openVideo(v)">
              <div class="vthumb" :style="v.thumb_url ? { backgroundImage: `url(${v.thumb_url})` } : {}">
                <span class="pick" @click.stop="toggleSel(v.id)"><Icon name="check" :size="12" /></span>
                <a class="dl" :href="`/api/videos/${v.id}/raw?download=1`" :download="v.filename" title="下载到本机" @click.stop>
                  <Icon name="download" :size="14" />
                </a>
                <button class="del" title="删除" @click.stop="openDelVideo([v.id], [v.filename])">
                  <Icon name="trash" :size="14" />
                </button>
                <span class="dur">{{ fmtDur(v.duration) }}</span>
              </div>
              <div class="vinfo">
                <div class="vname">{{ v.filename }}</div>
                <div class="vmeta">
                  <span>{{ fmtSize(v.size) }}</span>
                  <span v-if="v.tag_name" class="tag" :style="{ '--c': v.tag_color || '#8d98a8' }">{{ v.tag_name }}</span>
                  <span v-else class="badge gray">未打标签</span>
                  <span v-if="v.organized" class="badge green" style="margin-left:auto">已整理</span>
                </div>
              </div>
            </div>
            </div>
            <div v-else class="lib-empty">这个分组里还没有视频</div>
          </div>
          <div v-if="!videos.length && !libLoading" class="empty">没有符合条件的视频</div>
          <div v-if="sel.size" class="bulk">
            <Icon name="check" :size="15" style="color:var(--accent)" />
            <b>已选 {{ sel.size }} 个</b>
            <div class="sp" />
            <span style="font-size:12px;color:var(--muted-2)">批量打标签：</span>
            <button v-for="t in tags" :key="t.id" class="chip" @click="bulkTag(t.id)">
              <span class="dot" :style="{ background: t.color }" />{{ t.name }}
            </button>
            <button class="btn danger sm" @click="openDelVideo([...sel], videos.filter((v) => sel.has(v.id)).map((v) => v.filename))">
              <Icon name="trash" :size="14" />删除
            </button>
            <button class="btn ghost sm" @click="sel.clear()">取消</button>
          </div>
        </template>

        <!-- ================= 标签管理 ================= -->
        <template v-else-if="view === 'tags'">
          <div class="m-head">
            <div>
              <div class="m-title">标签管理</div>
              <div class="m-desc">每个标签对应一个目的文件夹；不填则默认在源目录下建同名文件夹。点「扫描」可同时扫描源文件夹与这些标签文件夹。</div>
            </div>
            <div class="sp" />
            <button class="btn ghost" :disabled="scan.running" title="同时扫描源文件夹与各标签的目标文件夹" @click="runScan">
              <Icon name="refresh" :size="15" />{{ scan.running ? '扫描中…' : '扫描' }}
            </button>
            <button class="btn primary" @click="openTag()"><Icon name="plus" :size="15" />新建标签</button>
          </div>
          <div class="rows">
            <div v-for="t in tags" :key="t.id" class="trow" :class="'st-' + (tagState[t.id] || 'idle')">
              <input class="inline-name" v-model="draftOf(t).name" spellcheck="false" title="标签名称" @input="queueSave(t.id)" @keyup.enter="saveTagInline(t.id)" />
              <button class="tag-color" :style="{ background: draftOf(t).color }" :title="`颜色 ${draftOf(t).color}（点击修改）`" @click.stop="toggleColorPop(t.id)" />
              <span class="ct">{{ t.count ?? 0 }} 个视频</span>
              <input class="inline-dir" v-model="draftOf(t).dir_path" :placeholder="t.effective_dir" :title="t.dir_path || t.effective_dir" spellcheck="false" @input="queueSave(t.id)" @keyup.enter="saveTagInline(t.id)" />
              <span class="save-hint">
                <span v-if="tagState[t.id] === 'saving'">保存中…</span>
                <span v-else-if="tagState[t.id] === 'saved'" class="ok">已保存</span>
                <span v-else-if="tagState[t.id] === 'err'" class="err">保存失败</span>
              </span>
              <button class="icon-act dg" title="删除" @click="delTag.tag = t; delTag.show = true"><Icon name="trash" :size="15" /></button>

              <div v-if="colorPop.id === t.id" class="color-pop" @click.stop>
                <div class="cp-grid">
                  <button v-for="c in TAG_COLORS" :key="c" class="swatch" :class="{ on: draftOf(t).color.toLowerCase() === c.toLowerCase() }" :style="{ background: c }" @click="setColor(t.id, c)" />
                </div>
                <div class="cp-custom">
                  <label>自定义</label>
                  <input type="color" :value="normalizeHex(draftOf(t).color) || '#8d98a8'" @input="onColorPicker(t.id, $event)" />
                  <input class="cp-hex" :value="draftOf(t).color" maxlength="7" spellcheck="false" @input="onHexInput(t.id, $event)" />
                </div>
              </div>
            </div>
            <div v-if="!tags.length" class="empty">还没有标签</div>
          </div>
        </template>

        <!-- ================= 整理 ================= -->
        <template v-else-if="view === 'organize'">
          <div class="m-head">
            <div>
              <div class="m-title">整理</div>
              <div class="m-desc">把打过标签的视频移动到对应文件夹。播放页的「整理」页签也能做同样的事。</div>
            </div>
            <div class="sp" />
            <button class="btn ghost" :disabled="planLoading" @click="loadPlan"><Icon name="refresh" :size="15" />刷新预览</button>
          </div>
          <div class="org-wrap">
            <div>
              <div v-for="g in planGroups" :key="g.tag_id" class="group">
                <div class="group-head">
                  <span class="cbx" :class="{ on: selTags.has(g.tag_id) }" @click="toggleTag(g.tag_id)"><Icon name="check" :size="12" /></span>
                  <span class="dot" :style="{ background: g.color }" />
                  <span class="nm">{{ g.name }}</span>
                  <span class="ct">{{ g.items.length }} 个 · {{ fmtSize(g.items.reduce((a, b) => a + (b.size || 0), 0)) }}</span>
                  <span class="dir" :title="g.dir">→ {{ g.dir }}</span>
                </div>
                <div class="files">
                  <div v-for="f in g.items" :key="f.video_id" class="frow">
                    <span class="fn">{{ f.name }}</span>
                    <span v-if="f.renamed" class="rn">重名自动改名</span>
                    <span class="fp">{{ fmtSize(f.size) }}</span>
                  </div>
                </div>
              </div>
              <div v-if="!planGroups.length" class="empty">没有需要整理的视频。先给视频打标签（需要先扫描源文件夹）。</div>
            </div>
            <div class="org-side">
              <div class="card">
                <div class="card-head"><h2>执行</h2></div>
                <div class="card-body">
                  <div class="kv"><span class="k">已选视频</span><span class="v">{{ selItems.length }} 个</span></div>
                  <div class="kv"><span class="k">目标文件夹</span><span class="v">{{ planDirs }} 个</span></div>
                  <div class="kv"><span class="k">总大小</span><span class="v">{{ fmtSize(selBytes) }}</span></div>
                  <div style="display:flex;gap:8px;margin-top:12px">
                    <button class="btn ghost sm" @click="selectAll(true)">全选</button>
                    <button class="btn ghost sm" @click="selectAll(false)">全不选</button>
                  </div>
                  <button class="btn primary" style="width:100%;margin-top:10px" :disabled="!selItems.length || orgRun.running" @click="runOrganize">
                    <Icon name="move" :size="15" />{{ orgRun.running ? '正在移动…' : `移动到标签文件夹（${selItems.length}）` }}
                  </button>
                  <div v-if="orgRun.running || orgRun.percent > 0" class="scanbar">
                    <div class="track"><i :style="{ width: orgRun.percent + '%' }" /></div>
                    <span style="font-size:11.5px;color:var(--muted-2);min-width:110px">{{ orgRun.text }}</span>
                  </div>
                </div>
              </div>
              <div class="card" style="margin-top:14px">
                <div class="card-head"><h2>整理记录</h2></div>
                <div class="card-body">
                  <div v-for="r in records" :key="r.id" class="rec">
                    <div class="rt">
                      <b>{{ fmtTime(r.created_at) }} · {{ r.files ?? r.count ?? 0 }} 个</b>
                      <span>{{ (r.dirs || []).join(' / ') || '—' }}</span>
                    </div>
                    <button v-if="!r.undone" class="btn ghost sm" @click="undo(r.id)">撤销</button>
                    <span v-else class="badge">已撤销</span>
                  </div>
                  <div v-if="!records.length" class="empty">暂无记录</div>
                </div>
              </div>
            </div>
          </div>
        </template>

        <!-- ================= 播放历史 ================= -->
        <template v-else-if="view === 'history'">
          <div class="m-head">
            <div>
              <div class="m-title">播放历史</div>
              <div class="m-desc">看过的视频都在这里，点卡片继续看。右下角的 × 可以删掉这条记录。</div>
            </div>
            <div class="sp" />
            <button class="btn ghost" :disabled="!history.length" @click="clearHist"><Icon name="trash" :size="15" />清空历史</button>
          </div>
          <div class="grid">
            <div v-for="h in history" :key="h.id" class="vcard" @click="router.push({ path: '/', query: { v: String(h.id) } })">
              <div class="vthumb" :style="h.thumb_url ? { backgroundImage: `url(${h.thumb_url})` } : {}">
                <button class="vdel" title="删除这条记录" @click.stop="delHist(h.id)"><Icon name="close" :size="13" /></button>
                <span class="vwhen">{{ h.watched_at ? fmtTime(h.watched_at) : '—' }}</span>
                <span class="prog"><i :style="{ width: histPct(h) + '%' }" /></span>
              </div>
              <div class="vinfo">
                <div class="vname">{{ h.filename }}</div>
                <div class="vmeta">
                  <span>{{ fmtDur(h.duration) }}</span>
                  <span v-if="h.tag_name" class="tag" :style="{ '--c': h.tag_color || '#8d98a8' }">{{ h.tag_name }}</span>
                  <span style="margin-left:auto">{{ histPct(h) }}%</span>
                </div>
              </div>
            </div>
          </div>
          <div v-if="!history.length" class="hist-empty">还没有播放记录</div>
        </template>

        <!-- ================= 登录管理 ================= -->
        <template v-else-if="view === 'account'">
          <div class="m-head">
            <div>
              <div class="m-title">登录管理</div>
              <div class="m-desc">修改用户名与密码。修改密码后其他设备需要重新登录。</div>
            </div>
          </div>
          <div class="split">
            <div class="card">
              <div class="card-head"><h2>用户名</h2></div>
              <div class="card-body">
                <div class="form-row"><label>用户名（至少 2 个字符）</label>
                  <input v-model="acc.username" class="field" spellcheck="false" />
                </div>
                <button class="btn primary" @click="saveUsername">保存用户名</button>
              </div>
            </div>
            <div class="card">
              <div class="card-head"><h2>修改密码</h2></div>
              <div class="card-body">
                <div class="form-row"><label>当前密码</label>
                  <div class="input-wrap"><input v-model="acc.oldPass" class="field" :type="acc.showPass ? 'text' : 'password'" />
                    <button class="eye" @click="acc.showPass = !acc.showPass"><Icon :name="acc.showPass ? 'eye-off' : 'eye'" :size="15" /></button>
                  </div>
                </div>
                <div class="form-row"><label>新密码（至少 6 位）</label>
                  <input v-model="acc.newPass" class="field" :type="acc.showPass ? 'text' : 'password'" />
                </div>
                <div class="form-row"><label>确认新密码</label>
                  <input v-model="acc.newPass2" class="field" :type="acc.showPass ? 'text' : 'password'" />
                </div>
                <button class="btn primary" :disabled="accSaving" @click="savePassword">修改密码</button>
              </div>
            </div>
          </div>
          <div class="card" style="margin-top:14px">
            <div class="card-head"><h2>已登录的设备</h2><div class="sp" /><button class="btn ghost sm" @click="revokeAll">全部退出</button></div>
            <div class="card-body">
              <div v-for="(s, i) in sessions" :key="i" class="sess">
                <Icon name="shield" :size="15" style="color:var(--muted-2)" />
                <span style="flex:1">会话 {{ i + 1 }} · 登录于 {{ fmtTime(s.created_at) }}</span>
                <span style="color:var(--muted-2);font-size:11.5px">最近使用 {{ s.last_used_at ? fmtTime(s.last_used_at) : '—' }}</span>
              </div>
              <div v-if="!sessions.length" class="empty">暂无其它会话</div>
            </div>
          </div>
        </template>

        <!-- ================= 关于 ================= -->
        <template v-else>
          <div class="about-hero">
            <div class="about-logo"><Icon name="folder" :size="24" /></div>
            <div>
              <div style="font-size:17px;font-weight:700">视频整理</div>
              <div style="font-size:12.5px;color:var(--muted);margin-top:3px">VideoSorter · 自托管的视频扫描与标签整理工具</div>
              <a class="repo-link" href="https://github.com/mdjbn/video-sorter" target="_blank" rel="noopener">
                github.com/mdjbn/video-sorter ↗
              </a>
            </div>
          </div>
          <div class="split">
            <div class="card">
              <div class="card-head"><h2>项目信息</h2></div>
              <div class="card-body">
                <div class="kv"><span class="k">版本</span><span class="v">{{ info?.version || '1.3.4' }}</span></div>
                <div class="kv"><span class="k">项目仓库</span><span class="v"><a class="repo-a" href="https://github.com/mdjbn/video-sorter" target="_blank" rel="noopener">mdjbn/video-sorter</a></span></div>
                <div class="kv"><span class="k">问题反馈</span><span class="v"><a class="repo-a" href="https://github.com/mdjbn/video-sorter/issues" target="_blank" rel="noopener">GitHub Issues</a></span></div>
                <div class="kv"><span class="k">开源许可</span><span class="v">MIT</span></div>
                <div class="kv"><span class="k">网页端</span><span class="v">Vue 3 + Vite + TypeScript</span></div>
                <div class="kv"><span class="k">服务端</span><span class="v">Python + FastAPI + SQLite</span></div>
                <div class="kv"><span class="k">手机端</span><span class="v">Kotlin + Compose + Media3</span></div>
                <div class="kv"><span class="k">数据目录</span><span class="v">{{ info?.data_dir || '—' }}</span></div>
                <div class="kv"><span class="k">整理根目录</span><span class="v">{{ info?.root_dir || '（跟随标签设置）' }}</span></div>
              </div>
            </div>
            <div class="card">
              <div class="card-head"><h2>运行环境</h2></div>
              <div class="card-body">
                <div class="kv"><span class="k">平台</span><span class="v">{{ info?.platform || '—' }}</span></div>
                <div class="kv"><span class="k">Python</span><span class="v">{{ info?.python || '—' }}</span></div>
                <div class="kv"><span class="k">ffmpeg</span><span class="v">{{ info?.media_ready ? '已就绪' : '未找到（无法生成封面/转码）' }}</span></div>
                <div class="kv"><span class="k">ffmpeg 路径</span><span class="v">{{ info?.ffmpeg || '—' }}</span></div>
                <div class="kv"><span class="k">ffprobe 路径</span><span class="v">{{ info?.ffprobe || '—' }}</span></div>
              </div>
            </div>
          </div>
          <div class="card" style="margin-top:14px">
            <div class="card-head"><h2>更新日志</h2></div>
            <div class="card-body">
              <div class="log-item"><span class="dt">1.3.4</span><span>Windows 桌面端修复「英文等非中文系统启动即崩」（控制台编码打印中文报错导致服务端起不来）；发版自动产出 Windows 安装包（.exe / .msi）；新增 Docker 镜像，同时发布到 Docker Hub 与 GHCR（amd64 / arm64）；安卓安装包改用固定证书签名，以后升级可直接覆盖安装、不用卸载重装（这一版仍需卸载旧包一次）。</span></div>
              <div class="log-item"><span class="dt">1.3.3</span><span>网页端 HLS 播放也会续播了（需要转码的视频不再每次从头播）；整理时文件被占用（如正在播放）会先自动重试两次，仍不行就提示「文件正被占用，请关闭播放器后重试」；全新安装后新增第一个源目录，上传目录会自动跟到「&lt;源目录&gt;/手机上传」；会话列表会标出「当前设备」。</span></div>
              <div class="log-item"><span class="dt">1.3.2</span><span>修复上传目录会自我嵌套（每次重启/新增源目录都多套一层「手机上传」，导致上传的视频散落在多层目录）；升级后启动会自动收敛回一层。</span></div>
              <div class="log-item"><span class="dt">1.3.1</span><span>管理页「下载手机 App」改成强调色按钮，与「扫描全部」统一；窄屏自动显示为「下载 App」。</span></div>
              <div class="log-item"><span class="dt">1.3.0</span><span>顶栏新增「下载手机 App」按钮（可直接从服务器下载安卓安装包）；手机浏览器打开网页端会提示安装 App。</span></div>
              <div class="log-item"><span class="dt">1.2.0</span><span>网页端适配移动设备：窄屏侧栏收成抽屉（左上角菜单），内容单列、统计卡 2×2、标签行自动换行、视频网格自适应，播放页在手机上改为上下布局。</span></div>
              <div class="log-item"><span class="dt">1.1.4</span><span>标签名称框常显边框；目标文件夹框恢复撑满并贴近删除按钮；预设颜色扩到 12 个。</span></div>
              <div class="log-item"><span class="dt">1.1.3</span><span>标签颜色改为小圆角色块并挪到名称右边，目标文件夹输入框收窄。</span></div>
              <div class="log-item"><span class="dt">1.1.2</span><span>标签管理改为行内编辑：名称、颜色、目标文件夹都可以直接在卡片上改（自动保存）；颜色支持自定义取色。</span></div>
              <div class="log-item"><span class="dt">1.1.1</span><span>视频封面改为取每个视频的第一帧（旧封面会自动重建）；概览页四个统计卡片改为 2×2，与标签分布卡片同排、标签分布卡片固定尺寸。</span></div>
              <div class="log-item"><span class="dt">1.1.0</span><span>扫描会同时遍历源文件夹与各标签的目标文件夹；网页端「源文件夹」管理移到视频库页；标签管理页新增扫描按钮；手机端标签管理页也新增扫描按钮。</span></div>
              <div class="log-item"><span class="dt">1.0.11</span><span>整理过的视频重新扫描后仍留在媒体库；视频库按「源文件夹 / 标签文件夹」分组展示。</span></div>
              <div class="log-item"><span class="dt">1.0.10</span><span>fnOS 安装包：安装向导可选择服务端口；卸载时可选择保留或删除应用数据。</span></div>
              <div class="log-item"><span class="dt">1.0.9</span><span>筛选支持多标签（手机端与网页端都可同时勾选多个标签取并集）；手机端视频库筛选后播放器只播筛选结果，切回视频库筛选状态保留。</span></div>
              <div class="log-item"><span class="dt">1.0.8</span><span>修复网页播放页筛选（切换全部/未打标签/待整理/已整理/标签后列表实时刷新）；安卓播放器新增预加载（预取后 2 个视频开头数据与 HLS 切片，切换起播更快）。</span></div>
              <div class="log-item"><span class="dt">1.0.7</span><span>网页端播放页新增下载按钮；源文件夹管理显示「上传目录」角标且不可删除；视频库支持单条与批量删除（可选同时删除文件）；重新扫描后已删除文件的视频不再出现在视频库与播放列表。</span></div>
              <div class="log-item"><span class="dt">1.0.6</span><span>上传目录纳入源文件夹管理（可改路径、不可删除），扫描覆盖上传目录；网页端新增上传（多文件+进度）与下载；手机端修「删除文件后视频库不刷新」「磁盘文件被删后播放报错」、进度条按住即跟手、长按手势分区、传输历史多选删除、播放记录去重与「视频已删除」标记。</span></div>
              <div class="log-item"><span class="dt">1.0.5</span><span>修复视频封面与视频内容错乱：缩略图按视频 id 命名（原来同一毫秒扫描多个文件会撞名）、封面地址带版本号自动破缓存、历史脏封面自动重建。</span></div>
                <div class="log-item"><span class="dt">1.0.4</span><span>修复窗口较矮时左侧栏底部用户栏被裁切（侧栏导航可滚动、用户栏始终可见）。</span></div>
              <div class="log-item"><span class="dt">1.0.3</span><span>修复 .avi/.wmv 老容器转码失败（copy 失败自动回退完整转码）；静态资源不再被浏览器缓存，升级后立即生效；安卓端真机联调修 12 处。</span></div>
              <div class="log-item"><span class="dt">1.0.1</span><span>关于页展示项目仓库与问题反馈入口；打包信息里的开发者/发布者改为项目作者。</span></div>
              <div class="log-item"><span class="dt">1.0.0</span><span>首个公开版本：扫描源文件夹、播放器打标签、按标签整理并支持撤销、整理预览、播放历史、三档主题；安卓 App、Windows 桌面端、fnOS 应用包。</span></div>
            </div>
          </div>
        </template>
      </div>
    </main>

    <!-- 标签弹窗 -->
    <div v-if="tagModal.show" class="modal-mask show" @click.self="tagModal.show = false">
      <div class="modal">
        <h3>{{ tagModal.id ? '编辑标签' : '新建标签' }}</h3>
        <p>标签名将作为整理时的文件夹名（也可在下面指定绝对路径）。</p>
        <div class="form-row" style="margin-top:14px"><label>标签名称</label>
          <input v-model="tagModal.name" class="field" placeholder="例如：旅行 / 宠物" spellcheck="false" @keyup.enter="saveTag" />
        </div>
        <div class="form-row"><label>颜色</label>
          <div class="swatches">
            <button v-for="c in TAG_COLORS" :key="c" class="swatch" :class="{ on: tagModal.color === c }" :style="{ background: c }" @click="tagModal.color = c" />
          </div>
        </div>
        <div class="form-row"><label>目的文件夹（留空则自动）</label>
          <input v-model="tagModal.dir" class="field" placeholder="/volume1/videos/整理/旅行" spellcheck="false" />
        </div>
        <div class="modal-actions">
          <button class="btn ghost" @click="tagModal.show = false">取消</button>
          <button class="btn primary" :disabled="tagModal.saving" @click="saveTag">保存</button>
        </div>
      </div>
    </div>

    <!-- 下载手机 App -->
    <div v-if="appDl.show" class="modal-mask show" @click.self="appDl.show = false">
      <div class="modal app-dl">
        <h3>下载手机 App</h3>
        <p>安卓 App 支持上下滑刷视频、长按加速、上传下载；装好后会自动发现局域网里的服务器（也可以手动填地址）。</p>
        <div v-if="appDl.loading" class="app-dl-loading">正在查询安装包…</div>
        <template v-else-if="appDl.apps.length">
          <a
            v-for="a in appDl.apps"
            :key="a.name"
            class="app-dl-row"
            :href="a.url"
            :download="a.name"
          >
            <span class="ico"><Icon name="download" :size="16" /></span>
            <span class="txt">
              <b>{{ a.abi === 'arm64-v8a' ? '安卓版（64 位，推荐）' : a.abi === 'armeabi-v7a' ? '安卓版（32 位，老机型）' : '安卓版' }}</b>
              <i>{{ a.name }} · {{ fmtSize(a.size) }}</i>
            </span>
            <span class="go">下载</span>
          </a>
          <p class="app-dl-tip">下载后点开安装；若提示「未知来源」，在系统设置里允许浏览器安装应用即可。</p>
        </template>
        <p v-else class="app-dl-empty">服务器上还没有放安装包。可以到 GitHub Releases 下载，或把 APK 放进数据目录的 <code>apk/</code> 文件夹。</p>
        <div class="app-dl-foot">
          <a class="btn ghost" :href="appDl.releases" target="_blank" rel="noopener">GitHub Releases</a>
          <button class="btn primary" @click="appDl.show = false">关闭</button>
        </div>
      </div>
    </div>

    <!-- 删除标签确认 -->
    <div v-if="delTag.show" class="modal-mask show" @click.self="delTag.show = false">
      <div class="modal">
        <h3>删除标签「{{ delTag.tag?.name }}」？</h3>
        <p>只删除标签本身，视频文件不会动；这些视频会变成未打标签状态。</p>
        <div class="modal-actions">
          <button class="btn ghost" @click="delTag.show = false">取消</button>
          <button class="btn danger" @click="doDelTag">删除</button>
        </div>
      </div>
    </div>

    <!-- 删除视频确认 -->
    <div v-if="delVideo.show" class="modal-mask show" @click.self="delVideo.show = false">
      <div class="modal">
        <h3>
          {{ delVideo.ids.length > 1 ? `删除选中的 ${delVideo.ids.length} 个视频？` : `删除「${delVideo.names[0]}」？` }}
        </h3>
        <p v-if="delVideo.ids.length > 1" class="mono" style="font-size:11.5px;color:var(--muted-2);max-height:90px;overflow:auto">
          {{ delVideo.names.join('、') }}
        </p>
        <label class="chk-row">
          <input v-model="delFile" type="checkbox" />
          <span>同时删除服务器上的文件（不可恢复）</span>
        </label>
        <p style="font-size:11.5px;color:var(--muted-2)">
          不勾选只从视频库里删掉这条记录，磁盘文件保留；勾选后文件也会被删除。
        </p>
        <div class="modal-actions">
          <button class="btn ghost" @click="delVideo.show = false">取消</button>
          <button class="btn danger" @click="doDelVideo">{{ delFile ? '删除记录和文件' : '仅删除记录' }}</button>
        </div>
      </div>
    </div>

    <!-- 退出登录确认 -->
    <div v-if="logoutModal" class="modal-mask show" @click.self="logoutModal = false">
      <div class="modal">
        <h3>退出登录？</h3>
        <p>退出后需要重新输入用户名和密码。</p>
        <div class="modal-actions">
          <button class="btn ghost" @click="logoutModal = false">取消</button>
          <button class="btn danger" @click="doLogout">退出登录</button>
        </div>
      </div>
    </div>
  </div>
</template>
