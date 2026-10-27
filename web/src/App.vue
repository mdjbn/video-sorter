<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import Login from './components/Login.vue'
import Icon from './components/Icon.vue'
import { api, onApiError } from './api'
import { toastState } from './toast'

const router = useRouter()
const ready = ref(false)
// 手机浏览器打开网页端时提示安装 App（安卓才提示；iOS 无法装 APK）
const promoDismissed = ref(true)
const promoApps = ref<{ name: string; abi: string; size: number; url: string }[]>([])
const promoReleases = ref('https://github.com/mdjbn/video-sorter/releases/latest')
const isAndroid = /Android/i.test(navigator.userAgent)
const showPromo = computed(() => isAndroid && !promoDismissed.value)
function dismissPromo(remember = true) {
  promoDismissed.value = true
  if (remember) {
    try { localStorage.setItem('vs_app_promo', '1') } catch { /* 隐私模式忽略 */ }
  }
}
async function loadPromo() {
  if (!isAndroid) return
  try {
    if (localStorage.getItem('vs_app_promo')) return
  } catch { /* 拿不到就当没关过 */ }
  promoDismissed.value = false
  try {
    const r = await fetch('/api/app/apk')
    const j = await r.json()
    promoApps.value = j.apps || []
    if (j.releases) promoReleases.value = j.releases
  } catch { /* 忽略，仍显示 GitHub 入口 */ }
}
const promoApk = computed(() => promoApps.value.find((a) => a.abi === 'arm64-v8a') || promoApps.value[0] || null)
const authed = ref(false)
const user = ref<{ id: number; username: string } | null>(null)
let off: (() => void) | null = null

async function check() {
  try {
    const res = await api.me()
    user.value = res.user
    authed.value = true
  } catch {
    authed.value = false
  } finally {
    ready.value = true
  }
}

onMounted(() => {
  check()
  loadPromo()
  off = onApiError((status) => {
    if (status === 401) {
      authed.value = false
      user.value = null
    }
  })
})
onUnmounted(() => off?.())

function onLogin(u: { id: number; username: string }) {
  user.value = u
  authed.value = true
  // 登录后进入播放页（用户要求：网页端以播放页为主页面）
  if (router.currentRoute.value.path !== '/') router.replace('/')
  else window.dispatchEvent(new CustomEvent('vs:logged-in'))
}

defineExpose({ user })
</script>

<template>
  <div v-if="!ready" class="boot">
    <div class="boot-mark">视频整理</div>
  </div>
  <template v-else>
    <router-view v-if="authed" :user="user" @logout="authed = false" />
    <Login v-else @ok="onLogin" />
  </template>

  <div v-if="showPromo" class="app-promo">
    <span class="promo-ico"><Icon name="download" :size="15" /></span>
    <div class="promo-txt">
      <b>用 App 刷视频更顺手</b>
      <span>上下滑切换、长按加速、自动发现服务器</span>
    </div>
    <a
      v-if="promoApk"
      class="promo-btn"
      :href="promoApk.url"
      :download="promoApk.name"
    >下载 App</a>
    <a v-else class="promo-btn" :href="promoReleases" target="_blank" rel="noopener">下载 App</a>
    <button class="promo-close" aria-label="关闭" @click="dismissPromo()"><Icon name="close" :size="14" /></button>
  </div>

  <div class="toast" :class="{ show: toastState.show, err: toastState.err }">
    <span class="tdot" />{{ toastState.text }}
  </div>
</template>

<style scoped>
.boot { height: 100%; display: grid; place-items: center; background: var(--bg); }
.boot-mark { color: var(--muted-2); font-size: 13px; letter-spacing: 6px; }
</style>
