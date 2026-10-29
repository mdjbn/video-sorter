/** 后端接口封装：同源 /api，cookie 登录态。 */

export type Video = {
  id: number
  path: string
  filename: string
  ext: string
  size: number
  duration: number
  width: number
  height: number
  vcodec: string
  acodec: string
  thumb_url: string | null
  raw_url: string
  tag_id: number | null
  tag_name: string | null
  tag_color: string | null
  status: 'idle' | 'tagged' | 'organized' | 'missing'
  organized: boolean
  has_tag: boolean
  /** 必须转码才能播（播放页 / 播放历史显示「转码」小标） */
  transcode?: boolean
  /** 为什么要转码，例如「HEVC 视频编码、AC3 音频编码…」 */
  transcode_reason?: string
  position?: number
  watched_at?: string
  added_at?: string
}

export type Tag = {
  id: number
  name: string
  color: string
  dir_path: string
  sort_order: number
  count: number
  default_dir: string
  effective_dir: string
}

export type Source = {
  id: number
  path: string
  enabled: number
  last_scan_at: string
  count: number
  /** '' 普通源目录；'upload' 内置上传目录（可改路径、不可删除） */
  kind?: string
  editable?: boolean
  deletable?: boolean
}

export type Stats = {
  total: number
  bytes: number
  tagged: number
  untagged: number
  organized: number
  tagged_pending: number
  missing: number
  last_scan_at: string
  tags: { id: number; name: string; color: string; count: number }[]
  sources: Source[]
}

export type Task = {
  id: string
  kind: string
  status: 'running' | 'done' | 'error' | 'cancelled'
  total: number
  done: number
  percent: number
  message: string
  result: any
  error: string
  started_at: string
  finished_at: string | null
}

export type PlanItem = {
  video_id: number
  name: string
  size: number
  duration: number
  tag_id: number
  tag_name: string
  tag_color: string
  from: string
  to: string
  dir: string
  renamed: boolean
  cross_device: boolean
}

export type Plan = {
  items: PlanItem[]
  total: number
  total_bytes: number
  skipped: number
  groups: { tag_id: number; tag_name: string; tag_color: string; dir: string; count: number; bytes: number }[]
}

export type HistoryItem = Video & { position: number; watched_at: string }

export type ImportResult = {
  ok: boolean
  applied: {
    settings: string[]
    sources_added: number
    sources_skipped: number
    tags_added: number
    tags_updated: number
  }
  settings: Record<string, any>
  restart_required: boolean
}

export type DirEntry = { name: string; path: string }

export type Info = {
  version: string
  data_dir: string
  platform: string
  python: string
  ffmpeg: string
  ffprobe: string
  media_ready: boolean
  root_dir: string
  web_dir: string
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

const listeners = new Set<(status: number) => void>()
export function onApiError(fn: (status: number) => void) {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { ...(init.headers as Record<string, string>) }
  if (init.body && !(init.body instanceof FormData)) headers['Content-Type'] = 'application/json'
  const res = await fetch(`/api${path}`, { credentials: 'include', ...init, headers })
  if (res.status === 204) return undefined as T
  const text = await res.text()
  let data: any = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    data = { detail: text }
  }
  if (!res.ok) {
    const msg = data?.detail || `请求失败（${res.status}）`
    if (res.status === 401) listeners.forEach((f) => f(401))
    throw new ApiError(res.status, typeof msg === 'string' ? msg : JSON.stringify(msg))
  }
  return data as T
}

const get = <T>(p: string) => request<T>(p)
const post = <T>(p: string, body?: any) =>
  request<T>(p, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })
const put = <T>(p: string, body?: any) =>
  request<T>(p, { method: 'PUT', body: body === undefined ? undefined : JSON.stringify(body) })
const patch = <T>(p: string, body?: any) =>
  request<T>(p, { method: 'PATCH', body: JSON.stringify(body) })
const del = <T>(p: string) => request<T>(p, { method: 'DELETE' })

export const api = {
  // 认证
  login: (username: string, password: string, remember = true) =>
    post<{ token: string; user: { id: number; username: string } }>('/auth/login', { username, password, remember }),
  logout: () => post<{ ok: boolean }>('/auth/logout'),
  me: () => get<{ user: { id: number; username: string } }>('/auth/me'),
  changePassword: (old_password: string, new_password: string) =>
    post<{ ok: boolean; message: string }>('/auth/password', { old_password, new_password }),
  changeUsername: (username: string) => post<{ ok: boolean; message: string }>('/auth/username', { username }),
  sessions: () => get<{ sessions: { token: string; created_at: string; last_used_at: string; current: boolean }[] }>('/auth/sessions'),
  revokeAll: () => post<{ ok: boolean }>('/auth/revoke-all'),

  // 设置/信息
  settings: () => get<{ settings: Record<string, any>; defaults: Record<string, any> }>('/settings'),
  saveSettings: (patchBody: Record<string, any>) => put<{ ok: boolean; settings: Record<string, any> }>('/settings', patchBody),
  /** 备份设置：返回下载地址（带 cookie 直接下载 JSON 文件） */
  exportSettingsUrl: () => '/api/settings/export',
  /** 导入设置：把备份的 JSON 套回来 */
  importSettings: (payload: any) => post<ImportResult>('/settings/import', payload),
  info: () => get<Info>('/info'),
  apkList: () =>
    get<{ version: string; apps: { name: string; abi: string; version: string; size: number; url: string }[]; releases: string }>('/app/apk'),
  stats: () => get<Stats>('/stats'),

  // 源目录
  sources: () => get<{ sources: Source[] }>('/sources'),
  addSource: (path: string) => post<{ ok: boolean; source: Source }>('/sources', { path }),
  removeSource: (id: number) =>
    del<{ ok: boolean; removed: string; videos_removed: number }>(`/sources/${id}`),
  updateSource: (id: number, path: string) => put<{ ok: boolean; source: Source }>(`/sources/${id}`, { path }),
  browse: (path?: string) => get<{ path: string; parent: string | null; dirs: DirEntry[] }>(`/fs/list${path ? `?path=${encodeURIComponent(path)}` : ''}`),
  fsRoots: () => get<{ roots: DirEntry[]; home: string }>('/fs/roots'),

  // 扫描/任务
  scan: (body: { source_ids?: number[]; tag_ids?: number[]; full?: boolean } = {}) =>
    post<{ task_id: string }>('/scan', body),
  task: (id: string) => get<Task>(`/tasks/${id}`),
  cancelTask: (id: string) => post<{ ok: boolean }>(`/tasks/${id}/cancel`),

  // 标签
  tags: () => get<{ tags: Tag[] }>('/tags'),
  createTag: (body: { name: string; color?: string; dir_path?: string }) =>
    post<{ ok: boolean; tag: Tag }>('/tags', body),
  updateTag: (id: number, body: Partial<{ name: string; color: string; dir_path: string }>) =>
    put<{ ok: boolean; tag: Tag }>(`/tags/${id}`, body),
  deleteTag: (id: number) => del<{ ok: boolean; released: number }>(`/tags/${id}`),
  /** 拖拽排序：把完整的标签 id 顺序发给服务端，服务端只改 sort_order */
  reorderTags: (ids: number[]) => put<{ ok: boolean; order: number[]; tags: Tag[] }>('/tags/order', { ids }),

  // 视频
  videos: (q: {
    status?: string
    tag?: string | number
    tags?: string
    q?: string
    sort?: string
    order?: string
    limit?: number
    offset?: number
  } = {}) => {
    const sp = new URLSearchParams()
    Object.entries(q).forEach(([k, v]) => {
      if (v !== undefined && v !== '' && v !== null) sp.set(k, String(v))
    })
    const qs = sp.toString()
    return get<{ items: Video[]; total: number; counts: Record<string, number> }>(`/videos${qs ? `?${qs}` : ''}`)
  },
  video: (id: number) => get<Video>(`/videos/${id}`),
  setTag: (id: number, tag_id: number | null) => post<Video>(`/videos/${id}/tag`, { tag_id }),
  renameVideo: (id: number, name: string) => post<Video>(`/videos/${id}/rename`, { name }),
  deleteVideo: (id: number, file = false) => del<{ ok: boolean; file_removed: boolean }>(`/videos/${id}?file=${file ? 1 : 0}`),
  play: (id: number) => get<{ mode: 'direct' | 'hls' | 'missing' | 'error'; url?: string; status?: string; percent?: number; duration?: number; message?: string; warning?: string; reason?: string }>(`/videos/${id}/play`),
  hlsStatus: (id: number, start = 0) =>
    get<{ status: string; percent: number; ready: boolean; finished: boolean; error: string }>(
      `/videos/${id}/hlsstatus${start > 0 ? `?start=${Math.floor(start)}` : ''}`,
    ),

  // 播放历史
  history: (limit = 60) => get<{ items: HistoryItem[] }>(`/history?limit=${limit}`),
  saveHistory: (id: number, position: number, duration: number) =>
    post<{ ok: boolean }>(`/videos/${id}/history`, { position, duration }),
  deleteHistory: (id: number) => del<{ ok: boolean }>(`/history/${id}`),
  clearHistory: () => del<{ ok: boolean }>('/history'),

  // 整理
  preview: (body: { tag_ids?: number[]; video_ids?: number[] } = {}) => post<Plan>('/organize/preview', body),
  execute: (body: { tag_ids?: number[]; video_ids?: number[] } = {}) =>
    post<{ task_id: string; planned: number; bytes: number }>('/organize/execute', body),
  records: (limit = 50) => get<{ items: { id: string; created_at: string; undone: number; note: string; files: number; dirs: string[] }[] }>(`/organize/records?limit=${limit}`),
  undo: (batchId: string) => post<{ restored: number; failed: { name: string; error: string }[] }>(`/organize/undo/${batchId}`),

  // 上传
  upload: (file: File, dir: string, tagId?: number | null) => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('dir', dir)
    if (tagId) fd.append('tag_id', String(tagId))
    return request<{ ok: boolean; video: Video; path: string }>('/upload', { method: 'POST', body: fd })
  },
}

/** 轮询任务直到结束 */
export async function waitTask(id: string, onTick?: (t: Task) => void, timeoutMs = 10 * 60 * 1000): Promise<Task> {
  const end = Date.now() + timeoutMs
  for (;;) {
    const t = await api.task(id)
    onTick?.(t)
    if (t.status !== 'running') return t
    if (Date.now() > end) throw new ApiError(408, '任务超时')
    await new Promise((r) => setTimeout(r, 350))
  }
}

export function fmtDur(sec?: number): string {
  const s = Math.max(0, Math.round(sec || 0))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const ss = s % 60
  const pad = (n: number) => String(n).padStart(2, '0')
  return h > 0 ? `${h}:${pad(m)}:${pad(ss)}` : `${m}:${pad(ss)}`
}

export function fmtSize(bytes?: number): string {
  const b = bytes || 0
  if (b >= 1024 ** 3) return `${(b / 1024 ** 3).toFixed(2)} GB`
  if (b >= 1024 ** 2) return `${(b / 1024 ** 2).toFixed(1)} MB`
  if (b >= 1024) return `${(b / 1024).toFixed(0)} KB`
  return `${b} B`
}

export function basename(p: string): string {
  return p.split(/[\\/]/).filter(Boolean).pop() || p
}

export function fmtTime(iso?: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  const pad = (n: number) => String(n).padStart(2, '0')
  const today = new Date()
  const sameDay = d.toDateString() === today.toDateString()
  const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`
  if (sameDay) return `今天 ${hm}`
  return `${d.getMonth() + 1}-${pad(d.getDate())} ${hm}`
}
