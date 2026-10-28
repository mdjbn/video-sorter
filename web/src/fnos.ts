/**
 * fnOS 微应用（宿主 iframe）桥接：只有在宿主里才有目录选择器。
 *
 * 独立浏览器打开（Windows 桌面端 / Docker / 手机浏览器直连）时 `window.parent === window`，
 * 这时 SDK 的宿主通道握手会超时，所以延迟加载并只在这种情况下使用；
 * 其它环境请用内置的 DirPicker 弹窗兜底。
 */

type PickResult = { code: number; msg: string; data?: string[] } | undefined

type TrimAppLike = {
  isWeb: boolean
  isStandaloneWeb: boolean
  ready(): Promise<void>
  pickUserFile(params?: Record<string, unknown>): Promise<PickResult>
}

let sdkPromise: Promise<TrimAppLike | null> | null = null

/** 是否运行在 fnOS 宿主页面里（微应用 iframe）。 */
export function isFnosHost(): boolean {
  try {
    return typeof window !== 'undefined' && window.parent !== window
  } catch {
    return false
  }
}

async function loadSdk(): Promise<TrimAppLike | null> {
  if (!isFnosHost()) return null
  if (!sdkPromise) {
    sdkPromise = (async () => {
      try {
        const mod: any = await import('@trimjs/web-app')
        const sdk = new mod.TrimApp() as TrimAppLike
        if (sdk.isStandaloneWeb) return null
        await sdk.ready()
        return sdk
      } catch {
        return null
      }
    })()
  }
  return sdkPromise
}

/**
 * 调起 fnOS 宿主的目录选择器。
 * - 返回字符串：用户选好的绝对路径
 * - 返回 null：用户取消了
 * - 返回 undefined：当前环境没有宿主选择器（调用方应回退到内置目录浏览）
 */
export async function pickDirFromHost(
  opts: { title?: string; okText?: string } = {},
): Promise<string | null | undefined> {
  const sdk = await loadSdk()
  if (!sdk) return undefined
  try {
    const res = await sdk.pickUserFile({
      directory: true,
      title: opts.title || '选择文件夹',
      okText: opts.okText || '选择',
    })
    if (!res) return null
    if (res.code !== 0) return null
    const first = (res.data || [])[0]
    return first || null
  } catch {
    // 宿主里调用失败（版本太老 / 没授权）就退回内置浏览
    return undefined
  }
}
