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
