<script setup lang="ts">
const props = withDefaults(defineProps<{ name: string; size?: number | string; filled?: boolean }>(), {
  size: 18,
  filled: false,
})

// 统一 24×24 viewBox 的线性图标（描边由 <svg> 的 stroke 控制）
const paths: Record<string, string> = {
  play: '<path d="M7 4.5v15l12-7.5z"/>',
  pause: '<path d="M8.5 4.5v15M15.5 4.5v15"/>',
  rewind: '<path d="M11 6.5v11L3.5 12zM20.5 6.5v11L13 12z"/>',
  'chevron-left': '<path d="M15 5l-7 7 7 7"/>',
  'chevron-right': '<path d="M9 5l7 7-7 7"/>',
  'chevron-down': '<path d="M5 9l7 7 7-7"/>',
  'chevron-up': '<path d="M5 15l7-7 7 7"/>',
  grid: '<rect x="3.5" y="3.5" width="7" height="7" rx="1.6"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.6"/><rect x="3.5" y="13.5" width="7" height="7" rx="1.6"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.6"/>',
  list: '<path d="M8 6h12M8 12h12M8 18h12M3.5 6h.01M3.5 12h.01M3.5 18h.01"/>',
  filter: '<path d="M3.5 5.5h17l-6.6 7.6V19l-3.8 2v-7.9z"/>',
  sort: '<path d="M7 4v16M3.5 16.5L7 20l3.5-3.5M17 20V4M13.5 7.5L17 4l3.5 3.5"/>',
  sun: '<circle cx="12" cy="12" r="4.2"/><path d="M12 2.5v2.6M12 18.9v2.6M4.2 4.2l1.9 1.9M17.9 17.9l1.9 1.9M2.5 12h2.6M18.9 12h2.6M4.2 19.8l1.9-1.9M17.9 6.1l1.9-1.9"/>',
  moon: '<path d="M20.5 14.5A8.5 8.5 0 019.5 3.5a8.5 8.5 0 1011 11z"/>',
  auto: '<circle cx="12" cy="12" r="8.6"/><path d="M12 3.4v17.2" /><path d="M12 8.4a3.6 3.6 0 010 7.2z" fill="currentColor" stroke="none"/>',
  pin: '<path d="M12 17v5M9 10.8a2 2 0 01-1.1 1.8l-1.8.9A2 2 0 005 15.2V16a1 1 0 001 1h12a1 1 0 001-1v-.8a2 2 0 00-1.1-1.8l-1.8-.9A2 2 0 0115 10.8V7a1 1 0 011-1 2 2 0 000-4H8a2 2 0 000 4 1 1 0 011 1z"/>',
  expand: '<path d="M8 3.5H4.5A1 1 0 003.5 4.5V8M16 3.5h3.5a1 1 0 011 1V8M16 20.5h3.5a1 1 0 001-1V16M8 20.5H4.5a1 1 0 01-1-1V16"/>',
  trash: '<path d="M4 7h16M9.5 7V4.5h5V7M6.5 7l.9 12.4a1.6 1.6 0 001.6 1.6h6a1.6 1.6 0 001.6-1.6L17.5 7M10 11v6M14 11v6"/>',
  pen: '<path d="M16.4 3.9l3.7 3.7L8.3 19.4 4 20l.6-4.3z"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  check: '<path d="M20 6.5L9.5 17 4 11.5"/>',
  close: '<path d="M6 6l12 12M18 6L6 18"/>',
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
  folder: '<path d="M3.5 7.2a1.7 1.7 0 011.7-1.7h4l2 2.6h7.6a1.7 1.7 0 011.7 1.7v8.5a1.7 1.7 0 01-1.7 1.7H5.2a1.7 1.7 0 01-1.7-1.7z"/>',
  tag: '<path d="M20.5 13.3l-7.2 7.2a1.7 1.7 0 01-2.4 0l-7.2-7.2a1.7 1.7 0 01-.5-1.2V4.6a1.1 1.1 0 011.1-1.1h7.5c.45 0 .88.18 1.2.5l7.2 7.2a1.7 1.7 0 010 2.1z"/><circle cx="8.4" cy="8.4" r="1.4"/>',
  upload: '<path d="M12 16V4.5M7.5 9L12 4.5 16.5 9M4.5 15.5v3a1.5 1.5 0 001.5 1.5h12a1.5 1.5 0 001.5-1.5v-3"/>',
  download: '<path d="M12 4.5V16M7.5 11.5L12 16l4.5-4.5M4.5 15.5v3a1.5 1.5 0 001.5 1.5h12a1.5 1.5 0 001.5-1.5v-3"/>',
  search: '<circle cx="11" cy="11" r="6.6"/><path d="M16 16l4.5 4.5"/>',
  eye: '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="3"/>',
  'eye-off': '<path d="M4 4l16 16M9.9 5.8A9.6 9.6 0 0112 5.5c6 0 9.5 6.5 9.5 6.5a17 17 0 01-3.3 4.2M6.2 8.1A17 17 0 002.5 12s3.5 6.5 9.5 6.5c1 0 2-.2 2.9-.5"/>',
  undo: '<path d="M3.5 9.5h9a6 6 0 010 12H8M3.5 9.5l4-4M3.5 9.5l4 4"/>',
  clock: '<circle cx="12" cy="12" r="8.6"/><path d="M12 7.4V12l3.4 2.2"/>',
  settings: '<circle cx="12" cy="12" r="3.2"/><path d="M12 2.8l1.3 2.4 2.7-.7.6 2.7 2.6 1-.9 2.6 2.1 1.8-1.8 2.1 1 2.6-2.6.9-.5 2.7-2.7-.6-1.4 2.4-2.3-1.4-2.3 1.4-1.3-2.4-2.7.6-.6-2.7-2.6-1 .9-2.6-2.1-1.8 1.8-2.1-1-2.6 2.6-.9.5-2.7 2.7.6z"/>',
  info: '<circle cx="12" cy="12" r="8.6"/><path d="M12 10.6V17M12 7.6h.01"/>',
  logout: '<path d="M14.5 3.5h4a1.5 1.5 0 011.5 1.5v14a1.5 1.5 0 01-1.5 1.5h-4M10 16l-4-4 4-4M6 12h9"/>',
  user: '<circle cx="12" cy="8.2" r="3.8"/><path d="M4.8 20.2a7.4 7.4 0 0114.4 0"/>',
  refresh: '<path d="M20 11.5A8 8 0 005.6 6.4L4 8M4 12.5A8 8 0 0018.4 17.6L20 16"/><path d="M4 4.5V8h3.5M20 19.5V16h-3.5"/>',
  film: '<rect x="3" y="4.5" width="18" height="15" rx="2"/><path d="M7.5 4.5v15M16.5 4.5v15M3 12h18M3 8.2h4.5M3 15.8h4.5M16.5 8.2H21M16.5 15.8H21"/>',
  drive: '<rect x="3" y="5" width="18" height="6" rx="1.8"/><rect x="3" y="13" width="18" height="6" rx="1.8"/><path d="M7 8h.01M7 16h.01"/>',
  wifi: '<path d="M4 9.5a12 12 0 0116 0M7 13a8 8 0 0110 0M10 16.4a3.6 3.6 0 014 0"/><circle cx="12" cy="19.6" r="0.9" fill="currentColor" stroke="none"/>',
  more: '<circle cx="5.5" cy="12" r="1.4" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="1.4" fill="currentColor" stroke="none"/><circle cx="18.5" cy="12" r="1.4" fill="currentColor" stroke="none"/>',
  speed: '<path d="M12 20a8 8 0 118-8c0 2.2-.9 4.2-2.3 5.6"/><path d="M12 12l4.2-4.2"/><circle cx="12" cy="12" r="1.3" fill="currentColor" stroke="none"/>',
  download2: '<path d="M12 3.5v10M8.5 10L12 13.5 15.5 10M5 16.5v2A2 2 0 007 20.5h10a2 2 0 002-2v-2"/>',
  database: '<ellipse cx="12" cy="6" rx="7.5" ry="3"/><path d="M4.5 6v6c0 1.66 3.36 3 7.5 3s7.5-1.34 7.5-3V6M4.5 12v6c0 1.66 3.36 3 7.5 3s7.5-1.34 7.5-3v-6"/>',
  shield: '<path d="M12 3.5l7 2.5v6c0 4.2-3 7.2-7 8.5-4-1.3-7-4.3-7-8.5V6z"/><path d="M9 12l2.2 2.2L15.5 10"/>',
  archive: '<rect x="3.5" y="4" width="17" height="4.5" rx="1.2"/><path d="M5.5 8.5V19a1.5 1.5 0 001.5 1.5h10a1.5 1.5 0 001.5-1.5V8.5M10 12.5h4"/>',
  move: '<path d="M12 3.5v17M3.5 12h17M7 7.5L12 3.5l5 4M7 16.5L12 20.5l5-4M7.5 7L3.5 12l4 5M16.5 7l4 5-4 5"/>',
  warn: '<path d="M12 4.5L21 19.5H3z"/><path d="M12 10v4M12 16.6h.01"/>',
  grip: '<circle cx="9" cy="6" r="1.45" fill="currentColor" stroke="none"/><circle cx="15" cy="6" r="1.45" fill="currentColor" stroke="none"/><circle cx="9" cy="12" r="1.45" fill="currentColor" stroke="none"/><circle cx="15" cy="12" r="1.45" fill="currentColor" stroke="none"/><circle cx="9" cy="18" r="1.45" fill="currentColor" stroke="none"/><circle cx="15" cy="18" r="1.45" fill="currentColor" stroke="none"/>',
}

const body = () => paths[props.name] || paths.info
</script>

<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    :fill="filled ? 'currentColor' : 'none'"
    stroke="currentColor"
    :stroke-width="filled ? 0 : 1.9"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    v-html="body()"
  />
</template>
