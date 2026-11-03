import { reactive } from 'vue'

export const toastState = reactive<{ text: string; err: boolean; show: boolean }>({
  text: '',
  err: false,
  show: false,
})

let timer: number | undefined

export function toast(text: string, err = false) {
  toastState.text = text
  toastState.err = err
  toastState.show = true
  window.clearTimeout(timer)
  timer = window.setTimeout(() => (toastState.show = false), 2400)
}

export type QueueItem = { text: string; err: boolean }

/**
 * 逐条播放的提示。给「每个目录扫完弹一条」这类场景用：
 * 普通 toast() 是覆盖式（后一条立刻顶掉前一条），一次弹十几条等于只看得到最后一条。
 * 这里排成队列，一条显示完再上一条，每条停留时长按字数自适应（最少 1.6s）。
 */
export const toastQueue = reactive<{ items: QueueItem[] }>({ items: [] })

let playing = false

export function toastEach(text: string, err = false) {
  toastQueue.items.push({ text, err })
  if (!playing) void playQueue()
}

async function playQueue() {
  playing = true
  try {
    while (toastQueue.items.length) {
      const item = toastQueue.items[0]
      toast(item.text, item.err)
      const stay = Math.min(5200, Math.max(1600, 900 + item.text.length * 90))
      await new Promise<void>((r) => window.setTimeout(r, stay))
      toastQueue.items.shift()
    }
  } finally {
    playing = false
  }
}
