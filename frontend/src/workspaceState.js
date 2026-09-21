const TABS = new Set(['home', 'engineer', 'manager', 'knowledge', 'about'])
const FILTERS = new Set(['all', 'fail', 'retry_pass', 'first_pass', 'unknown'])
const SORTS = new Set([
  'latest_failure',
  'status_priority',
  'attempt_count',
  'failure_count',
  'station',
  'duration',
  'knowledge_match',
])
const VIEWS = new Set(['table', 'cards'])
const ENGINEER_COLUMNS = new Set(['product', 'failure', 'evidence', 'action'])
const URL_KEYS = ['job', 'tab', 'unit', 'family', 'drill_signature', 'station', 'host', 'lot', 'product', 'scope_lot', 'scope_station', 'start', 'end']

export const DEFAULT_ENGINEER_VIEW_STATE = Object.freeze({
  filter: 'all',
  serialFilter: 'all',
  searchQuery: '',
  sortBy: 'latest_failure',
  activeSignature: null,
  view: 'table',
  expanded: null,
  columns: ['product', 'failure', 'evidence', 'action'],
})

export const DEFAULT_MANAGER_SCOPE = Object.freeze({
  products: [],
  lots: [],
  stations: [],
  startTime: '',
  endTime: '',
})

const bounded = (value, maxLength = 240) => {
  if (typeof value !== 'string') return null
  const clean = value.trim()
  return clean && clean.length <= maxLength ? clean : null
}

const allowed = (value, choices, fallback) => choices.has(value) ? value : fallback

const boundedList = (values, limit = 1000) => Array.from(new Set(
  (Array.isArray(values) ? values : []).map((value) => bounded(value)).filter(Boolean),
)).slice(0, limit)

function normalizeDrillDown(value) {
  if (!value || typeof value !== 'object') return null
  const signature = bounded(value.signature)
  const stationId = bounded(value.station_id)
  const host = bounded(value.host)
  const lotId = bounded(value.lot_id)
  if (!signature && !stationId && !lotId) return null
  return {
    ...(signature ? { signature } : {}),
    ...(stationId ? { station_id: stationId } : {}),
    ...(host ? { host } : {}),
    ...(lotId ? { lot_id: lotId } : {}),
    attempt_ids: boundedList(value.attempt_ids),
    unit_ids: boundedList(value.unit_ids),
    label: bounded(value.label) || signature || lotId || [host, stationId].filter(Boolean).join(' / '),
  }
}

function normalizeManagerScope(value) {
  const scope = value && typeof value === 'object' ? value : {}
  return {
    products: boundedList(scope.products, 50),
    lots: boundedList(scope.lots, 50),
    stations: boundedList(scope.stations, 50),
    startTime: bounded(scope.startTime) || '',
    endTime: bounded(scope.endTime) || '',
  }
}

export function normalizeWorkspaceState(value = {}) {
  const engineer = value.engineer || {}
  return {
    tab: allowed(value.tab, TABS, 'home'),
    jobId: bounded(value.jobId),
    engineer: {
      filter: allowed(engineer.filter, FILTERS, DEFAULT_ENGINEER_VIEW_STATE.filter),
      serialFilter: bounded(engineer.serialFilter) || DEFAULT_ENGINEER_VIEW_STATE.serialFilter,
      searchQuery: typeof engineer.searchQuery === 'string' ? engineer.searchQuery : '',
      sortBy: allowed(engineer.sortBy, SORTS, DEFAULT_ENGINEER_VIEW_STATE.sortBy),
      activeSignature: bounded(engineer.activeSignature),
      view: allowed(engineer.view, VIEWS, DEFAULT_ENGINEER_VIEW_STATE.view),
      expanded: bounded(engineer.expanded),
      columns: engineer.columns == null
        ? [...DEFAULT_ENGINEER_VIEW_STATE.columns]
        : boundedList(engineer.columns).filter((value) => ENGINEER_COLUMNS.has(value)),
    },
    managerScope: normalizeManagerScope(value.managerScope),
    drillDown: normalizeDrillDown(value.drillDown),
  }
}

export function workspaceStorageKey(username) {
  return `cotrace-workspace:${String(username || '').trim().toLocaleLowerCase()}`
}

export function loadWorkspaceState(storage, username, search = '') {
  let saved = {}
  try {
    saved = JSON.parse(storage?.getItem(workspaceStorageKey(username)) || '{}')
  } catch {
    saved = {}
  }

  const params = new URLSearchParams(search)
  const fromUrl = {
    ...saved,
    tab: params.get('tab') || saved.tab,
    jobId: params.get('job') || saved.jobId,
    engineer: {
      ...(saved.engineer || {}),
      expanded: params.get('unit') || saved.engineer?.expanded,
      activeSignature: params.get('family') || saved.engineer?.activeSignature,
    },
    managerScope: {
      ...(saved.managerScope || {}),
      products: params.has('product') ? params.getAll('product') : saved.managerScope?.products,
      lots: params.has('scope_lot') ? params.getAll('scope_lot') : saved.managerScope?.lots,
      stations: params.has('scope_station') ? params.getAll('scope_station') : saved.managerScope?.stations,
      startTime: params.get('start') || saved.managerScope?.startTime,
      endTime: params.get('end') || saved.managerScope?.endTime,
    },
    drillDown: params.has('drill_signature') || params.has('station') || params.has('lot')
      ? {
          ...(saved.drillDown || {}),
          signature: params.get('drill_signature'),
          station_id: params.get('station'),
          host: params.get('host'),
          lot_id: params.get('lot'),
        }
      : saved.drillDown,
  }
  return normalizeWorkspaceState(fromUrl)
}

export function saveWorkspaceState(storage, username, value) {
  const normalized = normalizeWorkspaceState(value)
  const safeState = {
    ...normalized,
    engineer: { ...normalized.engineer, searchQuery: '' },
  }
  try {
    storage?.setItem(workspaceStorageKey(username), JSON.stringify(safeState))
  } catch {
    // The workspace remains usable when browser storage is unavailable.
  }
  return safeState
}

export function clearWorkspaceState(storage, username) {
  try {
    storage?.removeItem(workspaceStorageKey(username))
  } catch {
    // The caller still clears in-memory and URL state.
  }
}

export function workspaceSearch(value, currentSearch = '') {
  const state = normalizeWorkspaceState(value)
  const params = new URLSearchParams(currentSearch)
  URL_KEYS.forEach((key) => params.delete(key))
  if (state.jobId) params.set('job', state.jobId)
  if (state.tab !== 'home') params.set('tab', state.tab)
  if (state.engineer.expanded) params.set('unit', state.engineer.expanded)
  if (state.engineer.activeSignature) params.set('family', state.engineer.activeSignature)
  state.managerScope.products.forEach((value) => params.append('product', value))
  state.managerScope.lots.forEach((value) => params.append('scope_lot', value))
  state.managerScope.stations.forEach((value) => params.append('scope_station', value))
  if (state.managerScope.startTime) params.set('start', state.managerScope.startTime)
  if (state.managerScope.endTime) params.set('end', state.managerScope.endTime)
  if (state.drillDown?.signature) params.set('drill_signature', state.drillDown.signature)
  if (state.drillDown?.station_id) params.set('station', state.drillDown.station_id)
  if (state.drillDown?.host) params.set('host', state.drillDown.host)
  if (state.drillDown?.lot_id) params.set('lot', state.drillDown.lot_id)
  const query = params.toString()
  return query ? `?${query}` : ''
}