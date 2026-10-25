<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { api, ApiError } from '../api'
import { THEME_LABEL, THEME_ORDER, themeMode, setThemeMode, type ThemeMode } from '../theme'
import Icon from './Icon.vue'

const emit = defineEmits<{ (e: 'ok', user: { id: number; username: string }): void }>()

const username = ref('admin')
const password = ref('')
const remember = ref(true)
const showPass = ref(false)
const err = ref('')
const shake = ref(false)
const busy = ref(false)
const userInput = ref<HTMLInputElement | null>(null)

onMounted(() => userInput.value?.focus())

function applyMode(mode: ThemeMode) {
  setThemeMode(mode)
}

async function submit() {
  if (busy.value) return
  err.value = ''
  if (!username.value.trim() || !password.value) {
    err.value = '请输入用户名和密码'
    fail()
    return
  }
  busy.value = true
  try {
    const res = await api.login(username.value.trim(), password.value, remember.value)
    emit('ok', res.user)
  } catch (e) {
    err.value = e instanceof ApiError ? e.message : '登录失败，请检查服务器是否在运行'
    fail()
  } finally {
    busy.value = false
  }
}

function fail() {
  shake.value = true
  window.setTimeout(() => (shake.value = false), 420)
}

defineExpose({ submit })
</script>

<template>
  <div class="login-mask">
    <form class="login-card" :class="{ shake }" @submit.prevent="submit">
      <div class="brand">
        <div class="mark"><Icon name="film" :size="21" /></div>
        <div>
          <h2>视频整理</h2>
          <div class="sub">VIDEO SORTER</div>
        </div>
      </div>
      <p class="lead">登录后进入播放页，边看边打标签，点「整理」按标签把视频移动到对应文件夹。</p>

      <label class="lbl">用户名</label>
      <input id="loginUser" ref="userInput" v-model="username" class="field" autocomplete="username" placeholder="admin" spellcheck="false" />

      <label class="lbl">密码</label>
      <div class="pass-wrap">
        <input
          id="loginPass"
          v-model="password"
          class="field"
          :type="showPass ? 'text' : 'password'"
          autocomplete="current-password"
          placeholder="请输入密码"
        />
        <button type="button" class="eye" :title="showPass ? '隐藏密码' : '显示密码'" @click="showPass = !showPass">
          <Icon :name="showPass ? 'eye-off' : 'eye'" :size="16" />
        </button>
      </div>

      <label class="remember" @click.prevent="remember = !remember">
        <span class="cbx" :class="{ on: remember }"><Icon v-if="remember" name="check" :size="11" /></span>
        在这台设备上保持登录 7 天
      </label>

      <div class="err">{{ err }}</div>

      <button id="btnLogin" class="btn primary login-btn" type="submit" :disabled="busy">
        <Icon v-if="busy" name="refresh" :size="15" class="spin" />
        {{ busy ? '登录中…' : '登录' }}
      </button>

      <div class="theme-row">
        <span class="tl">主题</span>
        <div class="seg">
          <button
            v-for="m in THEME_ORDER"
            :key="m"
            type="button"
            :class="{ on: themeMode === m }"
            @click="applyMode(m)"
          >
            {{ THEME_LABEL[m] }}
          </button>
        </div>
      </div>
      <div class="hint">默认账号 <code>admin</code> / <code>admin1234</code>，首次登录后请在「登录管理」里修改。</div>
    </form>
  </div>
</template>

<style scoped>
.login-mask {
  position: fixed; inset: 0; z-index: 90;
  display: flex; align-items: center; justify-content: center;
  padding: 24px;
  background:
    radial-gradient(760px 460px at 18% 8%, rgba(53, 209, 138, 0.16), transparent 70%),
    radial-gradient(680px 420px at 84% 92%, rgba(123, 140, 255, 0.14), transparent 72%),
    var(--bg);
}
html[data-theme='light'] .login-mask {
  background:
    radial-gradient(760px 460px at 18% 8%, rgba(15, 162, 103, 0.14), transparent 70%),
    radial-gradient(680px 420px at 84% 92%, rgba(123, 140, 255, 0.12), transparent 72%),
    var(--bg);
}
.login-card {
  width: min(392px, 100%);
  padding: 26px;
  border-radius: 18px;
  background: var(--panel);
  border: 1px solid var(--line-2);
  box-shadow: var(--shadow);
}
.login-card.shake { animation: shake 0.4s ease; }
@keyframes shake {
  0%, 100% { transform: translateX(0); }
  20% { transform: translateX(-7px); }
  40% { transform: translateX(6px); }
  60% { transform: translateX(-4px); }
  80% { transform: translateX(3px); }
}
.brand { display: flex; align-items: center; gap: 11px; }
.mark {
  width: 40px; height: 40px; border-radius: 12px;
  display: grid; place-items: center; color: #04160d;
  background: linear-gradient(150deg, #57e6a5, var(--accent));
  box-shadow: 0 8px 20px rgba(53, 209, 138, 0.28);
}
.brand h2 { font-size: 17px; letter-spacing: 0.6px; }
.brand .sub { font-size: 10px; letter-spacing: 2.4px; color: var(--muted-2); margin-top: 1px; }
.lead { margin: 16px 0 20px; font-size: 12.5px; line-height: 1.75; color: var(--muted); }
.lbl { display: block; font-size: 12px; color: var(--muted); margin-bottom: 7px; }
.lbl + .field { margin-bottom: 14px; }
.pass-wrap { position: relative; margin-bottom: 14px; }
.pass-wrap .field { padding-right: 40px; }
.eye {
  position: absolute; right: 6px; top: 50%; transform: translateY(-50%);
  width: 28px; height: 28px; border-radius: 8px;
  display: grid; place-items: center; color: var(--muted);
}
.eye:hover { color: var(--text); background: rgba(var(--ink), 0.06); }
.remember {
  display: inline-flex; align-items: center; gap: 8px;
  font-size: 12px; color: var(--muted); cursor: pointer; user-select: none;
}
.cbx {
  width: 16px; height: 16px; border-radius: 5px; flex: none;
  border: 1px solid rgba(var(--ink), 0.24);
  display: grid; place-items: center; color: #04160d;
}
.cbx.on { background: var(--accent); border-color: var(--accent); }
.err { min-height: 18px; margin: 10px 0 4px; color: var(--danger); font-size: 12px; }
.login-btn { width: 100%; height: 40px; margin-top: 4px; }
.theme-row {
  display: flex; align-items: center; justify-content: space-between;
  margin-top: 18px; padding-top: 16px; border-top: 1px solid var(--line);
}
.theme-row .tl { font-size: 12px; color: var(--muted-2); }
.hint { margin-top: 12px; font-size: 11.5px; line-height: 1.8; color: var(--muted-2); }
.hint code { color: var(--accent); background: rgba(var(--ink), 0.06); padding: 1px 5px; border-radius: 5px; }
</style>
