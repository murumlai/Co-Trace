import assert from 'node:assert/strict'
import test from 'node:test'
import {
  clearWorkspaceState,
  loadWorkspaceState,
  saveWorkspaceState,
  resolveDrillDownSelection,
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
      targetMetric: 'latest_observed_unit_yield',
      targetPercent: '95',
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
  assert.equal(restored.managerScope.targetMetric, 'latest_observed_unit_yield')
  assert.equal(restored.managerScope.targetPercent, '95')
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

test('persists drill-down selectors without large identity arrays', () => {
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

  assert.equal(restored.drillDown.signature, 'sig-1')
  assert.equal(restored.drillDown.attempt_ids, undefined)
  assert.equal(restored.drillDown.unit_ids, undefined)
  assert.doesNotMatch(query, /attempt-1|SN-1/)
})

test('explicit history entries clear omitted scope instead of inheriting saved filters', () => {
  const storage = memoryStorage()
  saveWorkspaceState(storage, 'user', {
    tab: 'manager',
    jobId: 'old-job',
    managerScope: { products: ['P1'], lots: ['LOT-1'], stations: ['ST-1'] },
  })

  const restored = loadWorkspaceState(storage, 'user', '?job=new-job&tab=engineer')

  assert.equal(restored.jobId, 'new-job')
  assert.deepEqual(restored.managerScope.products, [])
  assert.deepEqual(restored.managerScope.lots, [])
  assert.deepEqual(restored.managerScope.stations, [])
})

test('reconstructs exact drill-down identities from a compact selector', () => {
  const attemptIds = Array.from({ length: 1205 }, (_, index) => `attempt-${index}`)
  const resolved = resolveDrillDownSelection({
    pareto: [{ signature: 'sig-1', count: 1205, attempt_ids: attemptIds, unit_ids: ['SN-1'] }],
  }, { signature: 'sig-1', label: 'Failure family' })

  assert.equal(resolved.exact, true)
  assert.equal(resolved.selected_attempt_count, 1205)
  assert.equal(resolved.attempt_ids.length, 1205)
  assert.deepEqual(resolved.unit_ids, ['SN-1'])
})

test('a bare history entry clears a saved investigation', () => {
  const storage = memoryStorage()
  saveWorkspaceState(storage, 'user', { tab: 'engineer', jobId: 'job-1' })

  const restored = loadWorkspaceState(storage, 'user', '', { navigation: true })

  assert.equal(restored.tab, 'home')
  assert.equal(restored.jobId, null)
})