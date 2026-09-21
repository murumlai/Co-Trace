import assert from 'node:assert/strict'
import test from 'node:test'
import { selectDroppedFiles } from './uploadSelection.js'

const file = (name, webkitRelativePath = '') => ({ name, webkitRelativePath })

test('preserves a folder containing a run log and nested zip evidence', () => {
  const dropped = [
    file('ftrunnerlog01.txt', 'ReviewLogs/RUN-01/ftrunnerlog01.txt'),
    file('trace.zip', 'ReviewLogs/RUN-01/trace.zip'),
  ]

  assert.deepEqual(selectDroppedFiles(dropped), { files: dropped, replace: true, error: '' })
})

test('preserves a folder without nested archives', () => {
  const dropped = [file('ftrunnerlog01.txt', 'ReviewLogs/RUN-01/ftrunnerlog01.txt')]

  assert.deepEqual(selectDroppedFiles(dropped), { files: dropped, replace: true, error: '' })
})

test('accepts one standalone zip as the complete selection', () => {
  const archive = file('batch.zip')

  assert.deepEqual(selectDroppedFiles([archive]), {
    files: [archive],
    replace: true,
    error: '',
  })
})

test('warns when multiple loose files accompany a zip', () => {
  const archive = file('batch.zip')
  const result = selectDroppedFiles([archive, file('second.zip'), file('notes.txt')])

  assert.deepEqual(result.files, [archive])
  assert.equal(result.replace, true)
  assert.equal(result.error, 'Only one .zip can be loaded at a time. 2 other files ignored.')
})

test('keeps loose text files and reports unsupported files', () => {
  const log = file('ftrunnerlog01.txt')
  const result = selectDroppedFiles([log, file('image.png')])

  assert.deepEqual(result.files, [log])
  assert.equal(result.replace, false)
  assert.equal(result.error, '1 file skipped - only .txt files can be added individually.')
})