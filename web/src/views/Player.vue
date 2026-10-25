<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, nextTick, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  api, ApiError, basename, fmtDur, fmtSize, fmtTime, waitTask,
  type Plan, type PlanItem, type Tag, type Video,
} from '../api'
import { toast } from '../toast'
import { nextThemeMode, setThemeMode, themeIcon, themeMode, THEME_LABEL } from '../theme'
import Icon from '../components/Icon.vue'
import '../styles/player.css'

const props = defineProps<{ user: { id: number; username: string } | null }>()
const router = useRouter()
const route = useRoute()

// ---------- 列表数据 ----------
const tags = ref<Tag[]>([])
const videos = ref<Video[]>([])
const counts = ref<Record<string, number>>({})
const current = ref<Video | null>(null)
const pane = ref<'list' | 'org'>('list')
type Filter = 'all' | 'idle' | 'tagged' | 'organized' | `tag:${number}`
const filter = ref<Filter>('all')
const filterOpen = ref(false)
const loading = ref(true)

const filterLabel = computed(() => {
  if (filter.value === 'all') return '全部视频'
  if (filter.value === 'idle') return '未打标签'
  if (filter.value === 'tagged') return '待整理'
  if (filter.value === 'organized') return '已整理'
  const id = Number(filter.value.split(':')[1])
  const t = tags.value.find((x) => x.id === id)
  return t ? t.name : '标签'
})
const listCountText = computed(() => {
  if (filter.value === 'all') return `未整理 ${counts.value.idle ?? 0}`
  return `${videos.value.length} 个 · ${filterLabel.value}`
})
const organizedCount = computed(() => videos.value.filter((v) => v.organized).length)
const pendingCount = computed(() => counts.value.tagged ?? 0)

async function loadTags() {
  const res = await api.tags()
  tags.value = res.tags
}

async function loadVideos(keepId?: number) {
  const q: any = {}
  if (filter.value === 'idle') q.status = 'idle'
  else if (filter.value === 'tagged') q.status = 'tagged'
  else if (filter.value === 'organized') q.status = 'organized'
  else if (filter.value.startsWith('tag:')) q.tag = filter.value.split(':')[1]
  const res = await api.videos({ ...q, limit: 2000, sort: 'added', order: 'asc' })
  videos.value = res.items
  counts.value = res.counts
  loading.value = false
  if (!res.items.length) {
    current.value = null
    teardown()
    return
  }
  const wanted = keepId ?? current.value?.id
  const found = res.items.find((v) => v.id === wanted)
  await selectVideo(found ? found.id : res.items[0].id, { keepPlaying: false, force: true })
}

// ---------- 播放 ----------
const stageEl = ref<HTMLElement | null>(null)
const videoEl = ref<HTMLVideoElement | null>(null)
const posterEl = ref<HTMLElement | null>(null)
const listEl = ref<HTMLElement | null>(null)

const playing = ref(false)
const curTime = ref(0)
const duration = ref(0)
const speed = ref(1)
const tempSpeed = ref<number | null>(null)
const pinned = ref(false)
const hideUI = ref(false)
const hud = reactive({ show: false, val: '', cap: '', pct: 0 })
const playMode = ref<'direct' | 'hls' | 'missing' | 'error' | 'loading'>('loading')
const hlsPercent = ref(0)
const hlsMsg = ref('')
const muted = ref(false)

let hls: any = null
let hideTimer: number | undefined
let hudTimer: number | undefined
let saveTimer: number | undefined
let hlsPoll: number | undefined
let wheelLock = 0

const effSpeed = computed(() => tempSpeed.value ?? speed.value)
const pct = computed(() => (duration.value > 0 ? (curTime.value / duration.value) * 100 : 0))
const posterStyle = computed(() => {
  const v = current.value
  if (!v) return {}
  if (v.thumb_url) return { backgroundImage: `url(${v.thumb_url})` }
  const h = ((v.id * 47) % 360 + 200) % 360
  return { backgroundImage: `linear-gradient(150deg, hsl(${h} 28% 26%), hsl(${(h + 40) % 360} 24% 14%))` }
})
const currentTag = computed(() => tags.value.find((t) => t.id === current.value?.tag_id) || null)

function teardown() {
  if (hls) {
    hls.destroy()
    hls = null
  }
  window.clearInterval(hlsPoll)
  const el = videoEl.value
  if (el) {
    el.pause()
    el.removeAttribute('src')
    el.load()
  }
  playing.value = false
}

async function selectVideo(id: number, opts: { keepPlaying?: boolean; force?: boolean } = {}) {
  if (!opts.force && current.value?.id === id) {
    if (opts.keepPlaying && !playing.value) void togglePlay(true)
    return
  }
  await saveProgress()
  teardown()
  const v = videos.value.find((x) => x.id === id) || (await api.video(id))
  current.value = v
  curTime.value = v.position || 0
  duration.value = v.duration || 0
  speed.value = 1
  tempSpeed.value = null
  if (opts.keepPlaying === false) hideUI.value = false
  await nextTick()
  await startPlayback(v)
  scrollActiveIntoView()
  if (opts.keepPlaying) void togglePlay(true)
}

function scrollActiveIntoView() {
  nextTick(() => {
    const el = listEl.value?.querySelector('.pl-item.active') as HTMLElement | null
    el?.scrollIntoView({ block: 'nearest' })
  })
}

async function startPlayback(v: Video) {
  playMode.value = 'loading'
  hlsPercent.value = 0
  hlsMsg.value = ''
  const el = videoEl.value
  if (!el) return
  let info
  try {
    info = await api.play(v.id)
  } catch (e) {
    playMode.value = 'error'
    toast(e instanceof ApiError ? e.message : '获取播放地址失败', true)
    return
  }
  if (info.mode === 'missing') {
    playMode.value = 'missing'
    return
  }
  if (info.mode === 'error') {
    playMode.value = 'error'
    hlsMsg.value = info.message || '无法播放'
    return
  }
  if (info.mode === 'direct' && info.url) {
    playMode.value = 'direct'
    if (info.warning) toast(info.warning)
    el.src = info.url
    el.playbackRate = effSpeed.value
    el.load()
    if (v.position && v.position > 3) {
      const seekTo = () => {
        try {
          el.currentTime = Math.min(v.position!, Math.max(0, duration.value - 2))
        } catch {}
        el.removeEventListener('loadedmetadata', seekTo)
      }
      el.addEventListener('loadedmetadata', seekTo)
    }
    return
  }
  // HLS：先等后端切出第一个分片，再交给 hls.js
  playMode.value = 'hls'
  hlsMsg.value = '正在转码为流式播放…'
  await waitHlsReady(v.id)
}

async function waitHlsReady(videoId: number) {
  window.clearInterval(hlsPoll)
  const tick = async () => {
    try {
      const s = await api.hlsStatus(videoId)
      hlsPercent.value = s.percent || 0
      if (s.status === 'error') {
        playMode.value = 'error'
        hlsMsg.value = s.error || '转码失败'
        window.clearInterval(hlsPoll)
        return
      }
      if (s.ready) {
        window.clearInterval(hlsPoll)
        attachHls(videoId)
      }
    } catch {
      /* 忽略轮询错误 */
    }
  }
  await tick()
  hlsPoll = window.setInterval(tick, 800)
}

async function attachHls(videoId: number) {
  const el = videoEl.value
  if (!el) return
  playMode.value = 'direct'
  const url = `/api/videos/${videoId}/hls/index.m3u8`
  if (el.canPlayType('application/vnd.apple.mpegurl')) {
    el.src = url
  } else {
    const mod = await import('hls.js')
    const Hls = mod.default
    if (Hls.isSupported()) {
      hls = new Hls({ enableWorker: true, maxBufferLength: 30 })
      hls.loadSource(url)
      hls.attachMedia(el)
    } else {
      el.src = url
    }
  }
  el.playbackRate = effSpeed.value
}

function togglePlay(force?: boolean) {
  const el = videoEl.value
  if (!el || !current.value || playMode.value === 'missing' || playMode.value === 'error') return
  if (playMode.value === 'hls') return
  const want = force ?? el.paused
  if (want) {
    el.play().catch(() => {
      el.muted = true
      muted.value = true
      el.play().catch(() => toast('浏览器阻止了自动播放，请再点一次', true))
    })
  } else {
    el.pause()
  }
}

function onPlay() {
  playing.value = true
  scheduleHide()
  window.clearInterval(saveTimer)
  saveTimer = window.setInterval(saveProgress, 5000)
}
function onPause() {
  playing.value = false
  hideUI.value = false
  window.clearInterval(saveTimer)
  void saveProgress()
}
function onTime() {
  const el = videoEl.value
  if (!el) return
  curTime.value = el.currentTime
  if (el.duration && isFinite(el.duration)) duration.value = el.duration
}
function onLoaded() {
  const el = videoEl.value
  if (el && el.duration && isFinite(el.duration)) duration.value = el.duration
}
function onEnded() {
  playing.value = false
  hideUI.value = false
  const idx = videos.value.findIndex((v) => v.id === current.value?.id)
  if (idx >= 0 && idx < videos.value.length - 1) {
    selectVideo(videos.value[idx + 1].id, { keepPlaying: true })
  }
}

async function saveProgress() {
  const el = videoEl.value
  const v = current.value
  if (!el || !v || !duration.value) return
  if (el.currentTime < 1) return
  try {
    await api.saveHistory(v.id, Math.round(el.currentTime), Math.round(duration.value))
  } catch {
    /* 进度保存失败不打扰用户 */
  }
}

// ---------- 主题 / 跳转 ----------
function cycleTheme() {
  const mode = nextThemeMode()
  setThemeMode(mode)
  toast(`主题：${THEME_LABEL[mode]}`)
}
function toManage() {
  router.push('/manage')
}

// ---------- 标签 ----------
async function pickTag(t: Tag) {
  if (!current.value) return
  const v = current.value
  const next = v.tag_id === t.id ? null : t.id
  try {
    const updated = await api.setTag(v.id, next)
    Object.assign(v, updated)
    const inList = videos.value.find((x) => x.id === v.id)
    if (inList) Object.assign(inList, updated)
    counts.value = (await api.videos({ limit: 1 })).counts
    toast(next ? `已标记为「${t.name}」` : '已取消标签')
    if (pane.value === 'org') await loadPlan()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '打标签失败', true)
  }
}

const newTag = reactive({ show: false, name: '', color: '#f4a259', err: '' })
const TAG_COLORS = ['#f4a259', '#ef5b7b', '#4cc9f0', '#9b8cff', '#8d98a8', '#35d18a', '#f2c14e', '#ef7d4f']
function openNewTag() {
  newTag.show = true
  newTag.name = ''
  newTag.color = TAG_COLORS[0]
  newTag.err = ''
}
async function createTagAndTag() {
  const name = newTag.name.trim()
  if (!name) return (newTag.err = '请输入标签名称')
  if (tags.value.some((t) => t.name === name)) return (newTag.err = '已存在同名标签')
  try {
    const res = await api.createTag({ name, color: newTag.color })
    tags.value.push(res.tag)
    newTag.show = false
    if (current.value) await pickTag(res.tag)
    toast(`已创建「${name}」`)
  } catch (e) {
    newTag.err = e instanceof ApiError ? e.message : '创建失败'
  }
}
const newTagPath = computed(() => {
  const base = '/volume1/videos/整理/'
  return base + (newTag.name.trim() || '新标签名')
})

// ---------- 重命名 / 删除 ----------
const rename = reactive({ show: false, value: '', err: '', busy: false })
function openRename() {
  if (!current.value) return
  rename.show = true
  rename.value = basename(current.value.path)
  rename.err = ''
  rename.busy = false
}
async function doRename() {
  if (!current.value || rename.busy) return
  const name = rename.value.trim()
  if (!name) return (rename.err = '文件名不能为空')
  rename.busy = true
  try {
    const updated = await api.renameVideo(current.value.id, name)
    Object.assign(current.value, updated)
    const inList = videos.value.find((x) => x.id === updated.id)
    if (inList) Object.assign(inList, updated)
    rename.show = false
    toast('已重命名')
  } catch (e) {
    rename.err = e instanceof ApiError ? e.message : '重命名失败'
  } finally {
    rename.busy = false
  }
}

const del = reactive({ show: false, file: true, busy: false })
function openDelete() {
  if (!current.value) return
  del.show = true
  del.file = true
  del.busy = false
}
async function doDelete() {
  if (!current.value || del.busy) return
  del.busy = true
  try {
    await api.deleteVideo(current.value.id, del.file)
    del.show = false
    toast(del.file ? '已删除视频和文件' : '已从视频库移除')
    await loadVideos()
    await refreshTags()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '删除失败', true)
  } finally {
    del.busy = false
  }
}

async function refreshTags() {
  await loadTags()
}

// ---------- 整理 ----------
const plan = ref<Plan | null>(null)
const planLoading = ref(false)
const selTags = ref<Set<number>>(new Set())
const orgTouched = ref(false)  // 用户手动勾选过后不再自动全选
const orgRunning = ref(false)
const orgPercent = ref(0)
const orgMsg = ref('')

const orgGroups = computed(() => {
  const p = plan.value
  if (!p) return []
  // 后端 groups 只用于汇总，这里始终按 items 重建，确保每个分组带 tag_id
  const map = new Map<number, any>()
  for (const it of p.items) {
    const g = map.get(it.tag_id) || { tag_id: it.tag_id, tag_name: it.tag_name, tag_color: it.tag_color, dir: it.dir, count: 0, bytes: 0 }
    g.count++
    g.bytes += it.size || 0
    map.set(it.tag_id, g)
  }
  return [...map.values()]
})
const selItems = computed<PlanItem[]>(() => (plan.value?.items || []).filter((i) => selTags.value.has(i.tag_id)))
const selBytes = computed(() => selItems.value.reduce((s, i) => s + (i.size || 0), 0))

async function loadPlan() {
  planLoading.value = true
  try {
    const p = await api.preview({})
    plan.value = p
    // 后端 groups 没有 tag_id，勾选集合只从 items 里取（一定有值）
    const allIds = new Set<number>(p.items.map((i) => i.tag_id).filter((x): x is number => x != null))
    if (!orgTouched.value) {
      selTags.value = new Set(allIds)
    } else {
      selTags.value = new Set([...selTags.value].filter((id) => allIds.has(id)))
    }
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '加载整理计划失败', true)
  } finally {
    planLoading.value = false
  }
}
function toggleTagGroup(id: number) {
  const next = new Set(selTags.value)
  next.has(id) ? next.delete(id) : next.add(id)
  selTags.value = next
  orgTouched.value = true
}
function selectAllTags(all: boolean) {
  selTags.value = all ? new Set(orgGroups.value.map((g) => g.tag_id)) : new Set()
  orgTouched.value = true
}
async function runOrganize() {
  if (orgRunning.value || !selTags.value.size) return
  orgRunning.value = true
  orgPercent.value = 0
  orgMsg.value = '正在整理…'
  try {
    const res = await api.execute({ tag_ids: [...selTags.value] })
    const task = await waitTask(res.task_id, (t) => {
      orgPercent.value = t.percent || 0
      orgMsg.value = t.message || `已处理 ${t.done}/${t.total}`
    })
    if (task.status === 'error') throw new Error(task.error || '整理失败')
    const moved = task.result?.moved ?? 0
    const failed = task.result?.failed ?? []
    toast(failed.length ? `已移动 ${moved} 个，失败 ${failed.length} 个` : `已整理 ${moved} 个视频`, failed.length > 0)
    orgTouched.value = false
    await Promise.all([loadVideos(current.value?.id), loadPlan(), refreshTags()])
  } catch (e) {
    toast(e instanceof Error ? e.message : '整理失败', true)
  } finally {
    orgRunning.value = false
    orgPercent.value = 0
  }
}

// ---------- 手势 ----------
let press: { x: number; y: number; t: number; long: boolean; speedMode: boolean; base: number; timer?: number } | null = null
const INTERACTIVE = 'button, input, .tag, .tool, .seek, .timebar, .modal-mask, .topbar, .fmenu, .org-row, .org-file, .pl-item, .side, .hud'

function hudShow(val: string, cap: string, p: number) {
  hud.show = true
  hud.val = val
  hud.cap = cap
  hud.pct = p
  window.clearTimeout(hudTimer)
  hudTimer = window.setTimeout(() => (hud.show = false), 900)
}
function setTempSpeed(v: number | null) {
  tempSpeed.value = v
  const el = videoEl.value
  if (el) el.playbackRate = effSpeed.value
  paintSpeedButton()
}
function paintSpeedButton() {
  const el = document.getElementById('btnSpeed')
  if (el) el.classList.toggle('on', speed.value !== 1)
}

function onPointerDown(e: PointerEvent) {
  if (e.button !== 0) return
  const target = e.target as HTMLElement
  if (target.closest(INTERACTIVE)) return
  showUI()
  press = { x: e.clientX, y: e.clientY, t: Date.now(), long: false, speedMode: false, base: speed.value }
  press.timer = window.setTimeout(() => {
    if (!press) return
    press.long = true
    if (videoEl.value?.paused) togglePlay(true)
    setTempSpeed(2)
    hudShow('2.0×', '长按加速 · 松开恢复', 50)
  }, 420)
}
function onPointerMove(e: PointerEvent) {
  if (!press) return
  const dx = e.clientX - press.x
  const dy = e.clientY - press.y
  if (press.long) {
    if (!press.speedMode && Math.abs(dx) > 8) press.speedMode = true
    if (press.speedMode) {
      const v = Math.min(4, Math.max(0.25, press.base + dx / 160))
      const rounded = Math.round(v * 10) / 10
      setTempSpeed(rounded)
      hudShow(`${rounded.toFixed(1)}×`, '左右拖动调速 · 松开固定', (rounded / 4) * 100)
    }
  } else if (Math.abs(dx) > 6 || Math.abs(dy) > 6) {
    // 未长按就移动 → 取消长按判定（避免误触发）
    window.clearTimeout(press.timer)
    press = null
  }
}
function onPointerUp() {
  if (!press) return
  const p = press
  window.clearTimeout(p.timer)
  press = null
  if (p.long) {
    if (p.speedMode) {
      const v = tempSpeed.value ?? speed.value
      speed.value = Math.round(v * 10) / 10
      setTempSpeed(null)
      toast(`已固定 ${speed.value.toFixed(1)}×`)
      paintSpeedButton()
    } else {
      setTempSpeed(null)
    }
    return
  }
  if (Date.now() - p.t < 420) togglePlay()
}

function onWheel(e: WheelEvent) {
  if (!videos.value.length) return
  const target = e.target as HTMLElement
  if (target.closest('.side, .modal-mask')) return
  const now = Date.now()
  if (now - wheelLock < 380) return
  wheelLock = now
  const idx = videos.value.findIndex((v) => v.id === current.value?.id)
  const next = idx + (e.deltaY > 0 ? 1 : -1)
  if (next < 0 || next >= videos.value.length) {
    toast(e.deltaY > 0 ? '已经是最后一个了' : '已经是第一个了')
    return
  }
  selectVideo(videos.value[next].id, { keepPlaying: playing.value })
}

// ---------- 拖动进度 ----------
const seeking = ref(false)
function seekTo(clientX: number) {
  const el = videoEl.value
  const bar = document.getElementById('seek')
  if (!el || !bar) return
  const rect = bar.getBoundingClientRect()
  const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width))
  if (duration.value) {
    el.currentTime = ratio * duration.value
    curTime.value = el.currentTime
  }
}
function startSeek(e: PointerEvent) {
  seeking.value = true
  ;(e.currentTarget as HTMLElement).classList.add('drag')
  ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
  seekTo(e.clientX)
}
function moveSeek(e: PointerEvent) {
  if (seeking.value) seekTo(e.clientX)
}
function endSeek(e: PointerEvent) {
  if (!seeking.value) return
  seeking.value = false
  ;(e.currentTarget as HTMLElement).classList.remove('drag')
  toast(`跳到 ${fmtDur(videoEl.value?.currentTime || 0)}`)
}

// ---------- 控件显隐 ----------
function showUI() {
  hideUI.value = false
  if (playing.value && !pinned.value) scheduleHide()
}
function scheduleHide() {
  window.clearTimeout(hideTimer)
  hideUI.value = false
  if (!playing.value || pinned.value) return
  hideTimer = window.setTimeout(() => {
    if (playing.value && !pinned.value) hideUI.value = true
  }, 2800)
}
function togglePin() {
  pinned.value = !pinned.value
  if (pinned.value) {
    window.clearTimeout(hideTimer)
    hideUI.value = false
    toast('控件已固定，不再自动隐藏')
  } else {
    toast('控件将自动隐藏')
    scheduleHide()
  }
}
function toggleFull() {
  const el = stageEl.value
  if (!el) return
  if (document.fullscreenElement) document.exitFullscreen()
  else el.requestFullscreen?.().catch(() => toast('当前浏览器不支持全屏', true))
}
function cycleSpeed() {
  const steps = [1, 1.25, 1.5, 2, 0.5, 0.75]
  const i = steps.indexOf(speed.value)
  speed.value = i === -1 ? 1 : steps[(i + 1) % steps.length]
  const el = videoEl.value
  if (el) el.playbackRate = effSpeed.value
  paintSpeedButton()
  toast(`播放速度 ${speed.value.toFixed(2).replace(/0$/, '')}×`)
}

// ---------- 键盘 ----------
function onKey(e: KeyboardEvent) {
  const tag = (e.target as HTMLElement)?.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA') return
  if (e.key === ' ') {
    e.preventDefault()
    togglePlay()
  } else if (e.key === 'ArrowRight') {
    if (videoEl.value) videoEl.value.currentTime = Math.min(duration.value, videoEl.value.currentTime + 5)
  } else if (e.key === 'ArrowLeft') {
    if (videoEl.value) videoEl.value.currentTime = Math.max(0, videoEl.value.currentTime - 5)
  } else if (e.key === 'f' || e.key === 'F') {
    toggleFull()
  } else if (e.key === 'p' || e.key === 'P') {
    togglePin()
  } else if (e.key === 'Escape') {
    if (rename.show) rename.show = false
    else if (del.show) del.show = false
    else if (newTag.show) newTag.show = false
    else if (document.fullscreenElement) document.exitFullscreen()
  }
}

function closeMenus(e: MouseEvent) {
  if (!(e.target as HTMLElement).closest('.filter')) filterOpen.value = false
}

onMounted(async () => {
  window.addEventListener('keydown', onKey)
  document.addEventListener('click', closeMenus)
  window.addEventListener('beforeunload', () => {
    void saveProgress()
  })
  try {
    const wanted = Number(route.query.v)
    await Promise.all([loadTags(), loadVideos(Number.isFinite(wanted) && wanted > 0 ? wanted : undefined)])
    await loadPlan()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '加载失败', true)
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey)
  document.removeEventListener('click', closeMenus)
  window.clearInterval(saveTimer)
  window.clearTimeout(hideTimer)
  window.clearInterval(hlsPoll)
  void saveProgress()
  teardown()
})

defineExpose({ selectVideo })
</script>

<template>
  <div class="app">
    <!-- ============ 播放区 ============ -->
    <main
      ref="stageEl"
      class="stage"
      :class="{ 'hide-ui': hideUI }"
      @pointerdown="onPointerDown"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointercancel="onPointerUp"
      @pointerleave="onPointerUp"
      @wheel.prevent="onWheel"
      @mousemove="showUI"
    >
      <div ref="posterEl" class="poster" :style="posterStyle" />
      <video
        ref="videoEl"
        class="vid"
        playsinline
        preload="metadata"
        @play="onPlay"
        @pause="onPause"
        @timeupdate="onTime"
        @loadedmetadata="onLoaded"
        @ended="onEnded"
      />

      <div class="topbar">
        <div class="brand-mini">
          <span class="mark"><Icon name="film" :size="15" /></span>
          <span>视频整理</span><span class="sep">/</span><span class="cur">播放</span>
        </div>
        <div class="hintpill">
          <kbd>滚轮</kbd>切换 <kbd>单击</kbd>暂停 <kbd>长按</kbd>2× <kbd>长按拖动</kbd>调速
        </div>
      </div>

      <!-- 转码 / 缺失提示 -->
      <div v-if="playMode === 'hls' || playMode === 'missing' || playMode === 'error'" class="center-note">
        <template v-if="playMode === 'hls'">
          <b>正在准备播放</b>
          <span>{{ hlsMsg }}（{{ Math.round(hlsPercent) }}%）</span>
          <div class="nb"><i :style="{ width: Math.max(4, hlsPercent) + '%' }" /></div>
        </template>
        <template v-else-if="playMode === 'missing'">
          <b>文件不在了</b>
          <span>这个视频可能已被移动或删除。<br />可以点侧栏其他视频继续，或到管理页重新扫描。</span>
        </template>
        <template v-else>
          <b>无法播放</b>
          <span>{{ hlsMsg || '转码失败，请检查 ffmpeg 是否可用。' }}</span>
        </template>
      </div>

      <button v-if="!playing && playMode === 'direct'" class="big-play" @click="togglePlay(true)">
        <Icon name="play" :size="30" filled />
      </button>

      <div class="hud" :class="{ show: hud.show }">
        <div class="val">{{ hud.val }}</div>
        <div class="bar"><i :style="{ width: hud.pct + '%' }" /></div>
        <div class="cap">{{ hud.cap }}</div>
      </div>

      <div class="bottom">
        <div class="info-row">
          <div class="meta">
            <h1>
              <span>{{ current?.filename || '没有视频' }}</span>
              <span v-if="currentTag" class="tagbadge">
                <span class="dot" :style="{ background: currentTag.color }" />{{ currentTag.name }}
              </span>
              <span v-else-if="current" class="tagbadge" style="color: #f4a259">未打标签</span>
            </h1>
            <div class="path">{{ current?.path || '先到管理页添加源文件夹并扫描' }}</div>
          </div>
          <div class="tools">
            <button class="tool" :disabled="!current" @click="openRename"><Icon name="pen" :size="14" />重命名</button>
            <button class="tool" :disabled="!current" @click="openDelete"><Icon name="trash" :size="14" />删除</button>
            <span class="tool-sep" />
            <button id="btnSpeed" class="tool" :class="{ on: speed !== 1 }" @click="cycleSpeed">{{ speed.toFixed(1).replace(/\.0$/, '') }}×</button>
            <button class="tool icon" title="全屏（F）" @click="toggleFull"><Icon name="expand" :size="15" /></button>
            <button class="tool icon" :class="{ on: pinned }" title="固定控件（不再自动隐藏）" @click="togglePin">
              <Icon name="pin" :size="15" />
            </button>
          </div>
        </div>

        <div class="tags">
          <button
            v-for="t in tags"
            :key="t.id"
            class="tag"
            :class="{ on: current?.tag_id === t.id }"
            :style="{ '--c': t.color }"
            @click="pickTag(t)"
          >
            <span class="dot" />{{ t.name }}
          </button>
          <button class="tag new" @click="openNewTag"><Icon name="plus" :size="13" />新建标签</button>
        </div>

        <div class="timebar">
          <span class="tc">{{ fmtDur(curTime) }}</span>
          <div
            id="seek"
            class="seek"
            @pointerdown.stop="startSeek"
            @pointermove="moveSeek"
            @pointerup="endSeek"
            @pointercancel="endSeek"
          >
            <div class="track">
              <div class="fill" :style="{ width: pct + '%' }" />
              <span class="thumb" :style="{ left: pct + '%' }" />
            </div>
          </div>
          <span class="tc right">{{ fmtDur(duration || current?.duration) }}</span>
        </div>
      </div>
    </main>

    <!-- ============ 侧栏 ============ -->
    <aside class="side">
      <div class="pl-head">
        <div class="stabs">
          <button class="stab" :class="{ on: pane === 'list' }" @click="pane = 'list'">
            播放列表<i>{{ videos.length }}</i>
          </button>
          <button class="stab" :class="{ on: pane === 'org' }" @click="pane = 'org'; loadPlan()">
            整理<i>{{ plan?.total ?? pendingCount }}</i>
          </button>
        </div>
        <div class="acts">
          <button class="icon-btn" :title="`切换主题 · 当前：${THEME_LABEL[themeMode]}`" @click="cycleTheme">
            <Icon :name="themeIcon" :size="16" />
          </button>
          <button id="btnManage" class="icon-btn" title="管理页" @click="toManage"><Icon name="grid" :size="16" /></button>
        </div>
      </div>

      <!-- 播放列表 -->
      <div v-show="pane === 'list'" class="pane">
        <div class="filter">
          <button class="fbtn" :class="{ on: filter !== 'all', open: filterOpen }" @click.stop="filterOpen = !filterOpen">
            <Icon name="filter" :size="13" />
            <span>{{ filterLabel }}</span>
            <Icon name="chevron-down" :size="12" class="chev" />
          </button>
          <span class="fcount">{{ listCountText }}</span>
          <div v-if="filterOpen" class="fmenu">
            <button :class="{ on: filter === 'all' }" @click="filter = 'all'; filterOpen = false">
              全部视频<span class="cnt">{{ counts.all ?? 0 }}</span>
            </button>
            <button :class="{ on: filter === 'idle' }" @click="filter = 'idle'; filterOpen = false">
              未打标签<span class="cnt">{{ counts.idle ?? 0 }}</span>
            </button>
            <button :class="{ on: filter === 'tagged' }" @click="filter = 'tagged'; filterOpen = false">
              待整理<span class="cnt">{{ counts.tagged ?? 0 }}</span>
            </button>
            <button :class="{ on: filter === 'organized' }" @click="filter = 'organized'; filterOpen = false">
              已整理<span class="cnt">{{ counts.organized ?? 0 }}</span>
            </button>
            <div class="divider" />
            <button
              v-for="t in tags"
              :key="t.id"
              :class="{ on: filter === `tag:${t.id}` }"
              @click="filter = `tag:${t.id}`; filterOpen = false"
            >
              <span class="dot" :style="{ background: t.color }" />{{ t.name }}
              <span class="cnt">{{ t.count ?? 0 }}</span>
            </button>
          </div>
        </div>

        <div ref="listEl" class="pl-list">
          <div
            v-for="v in videos"
            :key="v.id"
            class="pl-item"
            :class="{ active: current?.id === v.id, playing: playing && current?.id === v.id, done: v.organized }"
            @click="selectVideo(v.id, { keepPlaying: true })"
          >
            <div
              class="pl-thumb"
              :style="v.thumb_url ? { backgroundImage: `url(${v.thumb_url})` } : {}"
            >
              <div class="eq"><i /><i /><i /></div>
              <span v-if="v.organized" class="pl-ok"><Icon name="check" :size="9" /></span>
              <span class="pl-dur">{{ fmtDur(v.duration) }}</span>
            </div>
            <div class="pl-info">
              <div class="pl-name">{{ v.filename }}</div>
              <div class="pl-sub2">
                <span v-if="v.tag_name" class="pl-tag" :style="{ '--c': v.tag_color || '#8d98a8' }">
                  <span class="dot" />{{ v.tag_name }}
                </span>
                <span v-else class="pl-tag none">未打标签</span>
                <span class="pl-dur2">{{ fmtSize(v.size) }}</span>
              </div>
            </div>
          </div>
          <div v-if="!videos.length && !loading" class="empty">
            <Icon name="film" :size="24" />
            <b>这里还没有视频</b>
            <span>到管理页添加源文件夹并扫描，视频就会出现在这个列表里。</span>
          </div>
        </div>

        <div class="pl-foot">
          <span>已整理 <b>{{ organizedCount }}</b> / {{ videos.length }}</span>
          <span class="live"><i />已连接</span>
        </div>
      </div>

      <!-- 整理 -->
      <div v-show="pane === 'org'" class="pane org">
        <div class="org-sum">
          可整理 <b>{{ plan?.total ?? 0 }}</b> 个 · {{ orgGroups.length }} 个文件夹
        </div>
        <div class="org-tip">
          勾选标签，下面会列出这些标签下还没整理的视频；点「开始整理」把文件移动到各自的目的文件夹（可在管理页修改每个标签的路径）。
        </div>
        <div class="org-list">
          <label v-for="g in orgGroups" :key="g.tag_id" class="org-row" @click.prevent="toggleTagGroup(g.tag_id)">
            <span class="cbx" :class="{ on: selTags.has(g.tag_id) }"><Icon v-if="selTags.has(g.tag_id)" name="check" :size="10" /></span>
            <span class="dot" :style="{ background: g.tag_color }" />
            <span class="nm">{{ g.tag_name }}</span>
            <span class="cnt">{{ g.count }}</span>
            <span class="pth" :title="g.dir">{{ '…/' + g.dir.split('/').filter(Boolean).slice(-2).join('/') }}</span>
          </label>

          <div v-if="orgGroups.length" class="pick-h">
            <span>将移动 <b>{{ selItems.length }}</b> 个视频 · {{ fmtSize(selBytes) }}</span>
            <span v-if="selItems.length === 0">勾选上方标签</span>
          </div>
          <div v-for="it in selItems" :key="it.video_id" class="org-file" @click="selectVideo(it.video_id)">
            <span class="fdot" :style="{ background: it.tag_color }" />
            <span class="fn" :title="it.name">{{ it.name }}</span>
            <span class="fp" :title="it.to">{{ '→ ' + it.dir.split('/').filter(Boolean).pop() + (it.renamed ? '（改名）' : '') }}</span>
          </div>

          <div v-if="!orgGroups.length" class="org-hint">
            <template v-if="planLoading">正在读取整理计划…</template>
            <template v-else>
              还没有可整理的视频。<br />先给视频打上标签，这里就会出现它们。
            </template>
          </div>
        </div>
        <div class="org-foot">
          <div v-if="orgRunning" class="org-prog"><i :style="{ width: Math.max(3, orgPercent) + '%' }" /></div>
          <div v-if="orgRunning" class="org-prog-txt">{{ orgMsg }}</div>
          <div class="org-actions">
            <button class="btn sm ghost" @click="selectAllTags(selTags.size !== orgGroups.length)">
              {{ selTags.size === orgGroups.length && orgGroups.length ? '全不选' : '全选' }}
            </button>
            <span class="sel"><b>{{ selItems.length }}</b> 个待移动</span>
            <button class="btn primary sm" :disabled="orgRunning || !selItems.length" @click="runOrganize">
              <Icon v-if="orgRunning" name="refresh" :size="14" class="spin" />
              {{ orgRunning ? '整理中…' : '开始整理' }}
            </button>
          </div>
        </div>
      </div>
    </aside>

    <!-- ============ 弹窗 ============ -->
    <div class="modal-mask" :class="{ show: rename.show }" @click.self="rename.show = false">
      <div class="modal">
        <h3>重命名视频</h3>
        <p>只改文件名，扩展名会自动保留；如果同目录已有同名文件会提示冲突。</p>
        <input v-model="rename.value" class="field mt" spellcheck="false" @keyup.enter="doRename" />
        <div class="err">{{ rename.err }}</div>
        <div class="modal-actions">
          <button class="btn ghost" @click="rename.show = false">取消</button>
          <button class="btn primary" :disabled="rename.busy" @click="doRename">确定</button>
        </div>
      </div>
    </div>

    <div class="modal-mask" :class="{ show: del.show }" @click.self="del.show = false">
      <div class="modal">
        <h3>删除这个视频？</h3>
        <p>{{ current?.filename }}</p>
        <label class="remember" style="margin-top: 14px; display: flex" @click.prevent="del.file = !del.file">
          <span class="cbx" :class="{ on: del.file }" style="display: grid; place-items: center">
            <Icon v-if="del.file" name="check" :size="10" />
          </span>
          同时删除磁盘上的文件（不可恢复）
        </label>
        <div class="modal-actions">
          <button class="btn ghost" @click="del.show = false">取消</button>
          <button class="btn danger" :disabled="del.busy" @click="doDelete">删除</button>
        </div>
      </div>
    </div>

    <div class="modal-mask" :class="{ show: newTag.show }" @click.self="newTag.show = false">
      <div class="modal">
        <h3>新建标签</h3>
        <p>标签名会成为整理时的文件夹名，可以在管理页的「标签管理」里改目的路径。</p>
        <input v-model="newTag.name" class="field mt" placeholder="例如：宠物 / 2025 旅行" maxlength="20" spellcheck="false" @keyup.enter="createTagAndTag" />
        <div class="swatches">
          <button
            v-for="c in TAG_COLORS"
            :key="c"
            class="swatch"
            :class="{ on: newTag.color === c }"
            :style="{ background: c }"
            @click="newTag.color = c"
          />
        </div>
        <div class="tagpath">默认整理路径：<b>{{ newTagPath }}</b></div>
        <div class="err">{{ newTag.err }}</div>
        <div class="modal-actions">
          <button class="btn ghost" @click="newTag.show = false">取消</button>
          <button class="btn primary" @click="createTagAndTag">创建并标记</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.remember { align-items: center; gap: 8px; font-size: 12.5px; color: var(--muted); cursor: pointer; }
.remember .cbx { width: 16px; height: 16px; border-radius: 5px; border: 1px solid rgba(var(--ink), 0.24); color: #04160d; }
.remember .cbx.on { background: var(--accent); border-color: var(--accent); }
.swatches { display: flex; gap: 10px; margin-top: 14px; }
.swatch { width: 26px; height: 26px; border-radius: 50%; border: 2px solid transparent; }
.swatch.on { border-color: var(--text); box-shadow: 0 0 0 3px rgba(var(--ink), 0.12); }
.tagpath {
  margin-top: 14px; padding: 10px 12px; border-radius: 9px;
  background: var(--input-bg); border: 1px solid var(--line);
  font-size: 11.5px; line-height: 1.6; color: var(--muted-2);
}
.tagpath b { color: var(--muted); font-weight: 500; word-break: break-all; }
</style>
