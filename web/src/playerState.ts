/** 播放页切到别处再回来时的现场快照。
 *
 * Player.vue 是路由级组件，切到 /manage 会被卸载，组件内所有 ref 都会丢；
 * 把「列表 + 当前视频 + 播放进度 + 筛选」存到模块级，回来时原地恢复，
 * 既不用重新拉一次全量列表（几千条要好几秒），也不会从第一个视频从头播。
 */
import type { Tag, Video } from './api'

export interface PlayerSnapshot {
  videos: Video[]
  counts: Record<string, number>
  tags: Tag[]
  currentId: number | null
  position: number
  status: string
  pickedTags: number[]
  playing: boolean
  at: number
}

let snap: PlayerSnapshot | null = null

export function readPlayerSnapshot(): PlayerSnapshot | null {
  return snap
}

export function writePlayerSnapshot(next: PlayerSnapshot) {
  snap = next
}

export function clearPlayerSnapshot() {
  snap = null
}
