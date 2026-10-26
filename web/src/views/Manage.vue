<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import Icon from '../components/Icon.vue'
import { api, fmtDur, fmtSize, fmtTime, waitTask, type HistoryItem, type PlanItem, type Source, type Stats, type Tag, type Video } from '../api'
import { toast } from '../toast'
import { nextThemeMode, setThemeMode, themeMode, themeNow } from '../theme'
import '../styles/manage.css'

const props = defineProps<{ user?: { username: string } | null }>()
const router = useRouter()

type View = 'overview' | 'library' | 'tags' | 'organize' | 'history' | 'account' | 'about'
const view = ref<View>('overview')
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
const lib = reactive({ status: 'all', tag: '' as string, q: '', mode: 'grid' as 'grid' | 'list' })
const videos = ref<Video[]>([])
const sel = reactive(new Set<number>())
const libLoading = ref(false)

const libChips = computed<any[]>(() => {
  const base = [
    { k: 'all', label: '全部' },
    { k: 'untagged', label: '未打标签' },
    { k: 'tagged', label: '待整理' },
    { k: 'organized', label: '已整理' },
  ]
  return [...base.map((b) => ({ ...b, v: b.k, on: lib.status === b.k && !lib.tag })),
    ...tags.value.map((t) => ({ k: `tag:${t.id}`, label: t.name, v: t.name, on: lib.tag === String(t.id), color: t.color }))]
})
function chipClick(c: any) {
  if (c.k.startsWith('tag:')) {
    const id = c.k.slice(4)
    lib.tag = lib.tag === id ? '' : id
    lib.status = 'all'
  } else {
    lib.status = c.k; lib.tag = ''
  }
  loadLibrary()
}
async function loadLibrary() {
  libLoading.value = true
  try {
    const r = await api.videos({
      status: lib.tag ? 'all' : lib.status,
      tag: lib.tag || undefined,
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

/* ---------------- 标签管理 ---------------- */
const tagModal = reactive({ show: false, id: 0, name: '', color: '#35d18a', dir: '', saving: false })
const TAG_COLORS = ['#f4a259', '#ef5b7b', '#4cc9f0', '#9b8cff', '#8d98a8', '#35d18a', '#f2c14e', '#ef7d4f']
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
async function doLogout() {
  try { await api.logout() } catch {}
  location.reload()
}

function cycleTheme() { setThemeMode(nextThemeMode()) }
const themeTitle = computed(() => `切换主题 · 当前：${themeNow.value}`)

onMounted(async () => {
  acc.username = username.value
  await Promise.all([loadTags(), loadStats(), loadSources(), loadRecords()])
  counts.lib = stats.value?.total || 0
})
</script>

<template>
  <div class="m-app">
    <aside class="m-side">
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
        <div class="m-crumb">视频整理 <span style="opacity:.4">/</span> <b>{{ VIEW_TITLE[view] }}</b></div>
        <div class="sp" />
        <button class="icon-btn" :title="themeTitle" @click="cycleTheme"><Icon :name="themeMode === 'auto' ? 'auto' : themeMode === 'light' ? 'sun' : 'moon'" :size="17" /></button>
      </div>

      <div class="m-scroll">
        <!-- ================= 概览 ================= -->
        <template v-if="view === 'overview'">
          <div class="m-head">
            <div>
              <div class="m-title">概览</div>
              <div class="m-desc">扫描源文件夹、给视频打标签，然后一键把带标签的视频移动到对应文件夹。</div>
            </div>
            <div class="sp" />
            <button class="btn primary" :disabled="scan.running" @click="runScan">
              <Icon name="refresh" :size="15" />{{ scan.running ? '扫描中…' : '扫描源文件夹' }}
            </button>
          </div>

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

          <div class="g2">
            <div class="card">
              <div class="card-head"><h2>源文件夹</h2><div class="sp" /><span class="badge">{{ sources.length }} 个</span></div>
              <div class="card-body">
                <div v-for="s in sources" :key="s.id" class="src-row">
                  <Icon name="folder" :size="17" style="color:var(--muted-2)" />
                  <div class="src-path">
                    <div class="p">{{ s.path }}</div>
                    <div class="s">{{ s.count ?? 0 }} 个视频 · 上次扫描 {{ s.last_scan_at ? fmtTime(s.last_scan_at) : '从未' }}</div>
                  </div>
                  <button class="icon-act dg" title="移除" @click="removeSource(s.id)"><Icon name="close" :size="15" /></button>
                </div>
                <div v-if="!sources.length" class="empty">还没有源文件夹，添加一个包含视频的目录。</div>
                <div style="display:flex;gap:8px;margin-top:12px">
                  <input v-model="newSource" class="field" placeholder="/volume1/videos/未整理" spellcheck="false" @keyup.enter="addSource" />
                  <button class="btn" @click="addSource">添加</button>
                </div>
                <div v-if="scan.running || scan.percent > 0" class="scanbar">
                  <div class="track"><i :style="{ width: scan.percent + '%' }" /></div>
                  <span style="font-size:11.5px;color:var(--muted-2);min-width:120px">{{ scan.text }}</span>
                </div>
              </div>
            </div>

            <div class="card">
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
            <button class="btn ghost" @click="go('overview')">去扫描</button>
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
          <div class="grid" :class="{ 'as-list': lib.mode === 'list' }">
            <div v-for="v in videos" :key="v.id" class="vcard" :class="{ sel: sel.has(v.id) }" @click="openVideo(v)">
              <div class="vthumb" :style="v.thumb_url ? { backgroundImage: `url(${v.thumb_url})` } : {}">
                <span class="pick" @click.stop="toggleSel(v.id)"><Icon name="check" :size="12" /></span>
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
          <div v-if="!videos.length && !libLoading" class="empty">没有符合条件的视频</div>
          <div v-if="sel.size" class="bulk">
            <Icon name="check" :size="15" style="color:var(--accent)" />
            <b>已选 {{ sel.size }} 个</b>
            <div class="sp" />
            <span style="font-size:12px;color:var(--muted-2)">批量打标签：</span>
            <button v-for="t in tags" :key="t.id" class="chip" @click="bulkTag(t.id)">
              <span class="dot" :style="{ background: t.color }" />{{ t.name }}
            </button>
            <button class="btn ghost sm" @click="sel.clear()">取消</button>
          </div>
        </template>

        <!-- ================= 标签管理 ================= -->
        <template v-else-if="view === 'tags'">
          <div class="m-head">
            <div>
              <div class="m-title">标签管理</div>
              <div class="m-desc">每个标签对应一个目的文件夹；不填则默认在视频所在目录/源目录下建同名文件夹。</div>
            </div>
            <div class="sp" />
            <button class="btn primary" @click="openTag()"><Icon name="plus" :size="15" />新建标签</button>
          </div>
          <div class="rows">
            <div v-for="t in tags" :key="t.id" class="trow">
              <span class="dot" :style="{ background: t.color }" />
              <span class="nm">{{ t.name }}</span>
              <span class="ct">{{ t.count ?? 0 }} 个视频</span>
              <span class="pth" :class="{ custom: !!t.dir_path }" :title="t.dir_path || t.effective_dir">{{ t.dir_path || t.effective_dir }}</span>
              <button class="icon-act" title="编辑" @click="openTag(t)"><Icon name="pen" :size="15" /></button>
              <button class="icon-act dg" title="删除" @click="delTag.tag = t; delTag.show = true"><Icon name="trash" :size="15" /></button>
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
            </div>
          </div>
          <div class="split">
            <div class="card">
              <div class="card-head"><h2>项目信息</h2></div>
              <div class="card-body">
                <div class="kv"><span class="k">版本</span><span class="v">{{ info?.version || '1.0.0' }}</span></div>
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
