// Built bundles live in <app root>/assets/, so this also resolves IIS sub-paths such as /cotrace.
const moduleUrl = new URL(import.meta.url)
const assetsIndex = moduleUrl.pathname.lastIndexOf('/assets/')
const APP_ROOT = /^https?:$/.test(moduleUrl.protocol) && assetsIndex >= 0 ? moduleUrl.pathname.slice(0, assetsIndex) : ''

export function appUrl(path) {
  return `${APP_ROOT}${path}`
}
