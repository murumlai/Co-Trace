import assert from 'node:assert/strict'
import test from 'node:test'
import {
  clearWorkspaceState,
  loadWorkspaceState,
  saveWorkspaceState,
  workspaceSearch,
  workspaceStorageKey,
} from './workspaceState.js'

function memoryStorage() {
  const values = new Map()
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  }
}

test('restores identifiers and preferences without persisting free-text search', () => {
  const storage = memoryStorage()
  saveWorkspaceState(storage, 'Engineer.One', {
    tab: 'engineer',
    jobId: 'job-123',
    engineer: {
      filter: 'fail',
      serialFilter: 'SERIAL-123',
      searchQuery: 'secret diagnosis text',
      sortBy: 'station',
      activeSignature: 'signature-1',
      view: 'cards',
      expanded: 'attempt-9',
      columns: ['product', 'failure'],
    },
    drillDown: { lot_id: 'LOT-A' },
    managerScope: {
      products: ['P1'],
      lots: ['LOT-A'],
      stations: ['station-key'],
      startTime: '2026-09-20T08:00',
      endTime: '2026-09-20T10:00',
    },
  })

  const restored = loadWorkspaceState(storage, 'engineer.one')
  assert.equal(restored.jobId, 'job-123')
  assert.equal(restored.tab, 'engineer')
  assert.equal(restored.engineer.filter, 'fail')
  assert.equal(restored.engineer.serialFilter, 'SERIAL-123')
  assert.equal(restored.engineer.searchQuery, '')
  assert.equal(restored.engineer.expanded, 'attempt-9')
  assert.deepEqual(restored.engineer.columns, ['product', 'failure'])
  assert.equal(restored.drillDown.lot_id, 'LOT-A')
  assert.deepEqual(restored.managerScope.products, ['P1'])
})

test('URL identifiers override the session workspace and preserve unrelated parameters', () => {
  const storage = memoryStorage()
  saveWorkspaceState(storage, 'user', { tab: 'home', jobId: 'old-job' })

  const restored = loadWorkspaceState(
    storage,
    'user',
    '?job=new-job&tab=manager&station=ST-02&host=TESTER-1&other=keep',
  )
  assert.equal(restored.jobId, 'new-job')
  assert.equal(restored.tab, 'manager')
  assert.equal(restored.drillDown.station_id, 'ST-02')
  assert.equal(restored.drillDown.host, 'TESTER-1')

  const query = workspaceSearch(restored, '?other=keep&job=old-job')
  assert.match(query, /other=keep/)
  assert.match(query, /job=new-job/)
  assert.match(query, /tab=manager/)
  assert.match(query, /scope_station=ST-02|station=ST-02/)
  assert.doesNotMatch(query, /old-job/)
})

test('invalid and oversized values fall back safely', () => {
  const storage = memoryStorage()
  storage.setItem(workspaceStorageKey('user'), JSON.stringify({
    tab: 'invalid',
    jobId: 'x'.repeat(241),
    engineer: { filter: 'invalid', sortBy: 'invalid', view: 'invalid' },
  }))

  const restored = loadWorkspaceState(storage, 'user')
  assert.equal(restored.tab, 'home')
  assert.equal(restored.jobId, null)
  assert.equal(restored.engineer.filter, 'all')
  assert.equal(restored.engineer.sortBy, 'latest_failure')
  assert.equal(restored.engineer.view, 'table')
})

test('workspace storage is identity scoped and removable on sign out', () => {
  const storage = memoryStorage()
  saveWorkspaceState(storage, 'first', { jobId: 'first-job' })
  saveWorkspaceState(storage, 'second', { jobId: 'second-job' })

  clearWorkspaceState(storage, 'first')
  assert.equal(loadWorkspaceState(storage, 'first').jobId, null)
  assert.equal(loadWorkspaceState(storage, 'second').jobId, 'second-job')
})

test('preserves exact drill-down identities in session state without putting them in the URL', () => {
  const storage = memoryStorage()
  const state = saveWorkspaceState(storage, 'user', {
    tab: 'engineer',
    jobId: 'job-1',
    drillDown: {
      signature: 'sig-1',
      attempt_ids: ['attempt-1', 'attempt-2'],
      unit_ids: ['SN-1'],
      label: 'Failure family',
    },
  })
  const query = workspaceSearch(state)
  const restored = loadWorkspaceState(storage, 'user', query)

  assert.deepEqual(restored.drillDown.attempt_ids, ['attempt-1', 'attempt-2'])
  assert.deepEqual(restored.drillDown.unit_ids, ['SN-1'])
  assert.doesNotMatch(query, /attempt-1|SN-1/)
})