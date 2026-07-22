import { spawn } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const scriptDir = path.dirname(fileURLToPath(import.meta.url))
const frontendRoot = path.resolve(scriptDir, '..')
const repoRoot = path.resolve(frontendRoot, '..')
const debug = process.argv.includes('--debug')
const viteArgs = process.argv.slice(2).filter((arg) => arg !== '--debug')
const logPath = process.env.FRONTEND_LOG_FILE || path.join(repoRoot, 'frontend_Log.txt')

fs.writeFileSync(
  logPath,
  `${JSON.stringify({
    ts: new Date().toISOString(),
    level: 'info',
    source: 'frontend-dev-server',
    message: 'frontend dev server starting',
    debug,
  })}\n`,
  'utf8',
)

const viteBin = path.join(frontendRoot, 'node_modules', '.bin', process.platform === 'win32' ? 'vite.cmd' : 'vite')
const child = spawn(viteBin, viteArgs, {
  cwd: frontendRoot,
  env: {
    ...process.env,
    VITE_COTRACE_DEBUG: debug ? '1' : process.env.VITE_COTRACE_DEBUG || '0',
  },
  shell: process.platform === 'win32',
  stdio: ['inherit', 'pipe', 'pipe'],
})

function mirror(chunk, stream) {
  stream.write(chunk)
  fs.appendFileSync(logPath, chunk)
}

child.stdout.on('data', (chunk) => mirror(chunk, process.stdout))
child.stderr.on('data', (chunk) => mirror(chunk, process.stderr))
child.on('exit', (code, signal) => {
  fs.appendFileSync(
    logPath,
    `\n${JSON.stringify({
      ts: new Date().toISOString(),
      level: code === 0 ? 'info' : 'error',
      source: 'frontend-dev-server',
      message: 'frontend dev server stopped',
      code,
      signal,
    })}\n`,
  )
  process.exit(code ?? 1)
})