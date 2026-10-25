<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import Login from './components/Login.vue'
import { api, onApiError } from './api'
import { toastState } from './toast'

const router = useRouter()
const ready = ref(false)
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

  <div class="toast" :class="{ show: toastState.show, err: toastState.err }">
    <span class="tdot" />{{ toastState.text }}
  </div>
</template>

<style scoped>
.boot { height: 100%; display: grid; place-items: center; background: var(--bg); }
.boot-mark { color: var(--muted-2); font-size: 13px; letter-spacing: 6px; }
</style>
