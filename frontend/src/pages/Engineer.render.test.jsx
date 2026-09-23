// @vitest-environment jsdom

import { useCallback, useState } from 'react'
import { act, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import { DEFAULT_ENGINEER_VIEW_STATE } from '../workspaceState'
import Engineer from './Engineer'

const apiMocks = vi.hoisted(() => ({
  actions: vi.fn(),
  clusters: vi.fn(),
  feedback: vi.fn(),
  units: vi.fn(),
}))

vi.mock('../api', () => ({ api: apiMocks }))
vi.mock('../auth', () => ({ useAuth: () => ({ isAdmin: false }) }))

const SELECTED_SIGNATURE = 'selected-manager-signature'
const CLUSTER_COUNT = 40

function cluster(index) {
  return {
    signature: index === 0 ? SELECTED_SIGNATURE : `signature-${index}`,
    count: CLUSTER_COUNT - index,
    error_code: `ERROR_${index}`,
    error_message: `Unique cluster detail ${index}`,
    stations: ['station-1'],
    lots: ['lot-1'],
    affected_serials: [`serial-${index}`],
    last_seen: '2026-09-23T12:00:00Z',
  }
}

function EngineerStateHarness({ onRender }) {
  const [viewState, setViewState] = useState(() => ({
    ...DEFAULT_ENGINEER_VIEW_STATE,
    columns: [...DEFAULT_ENGINEER_VIEW_STATE.columns],
  }))
  const updateViewState = useCallback((update) => setViewState(update), [])
  onRender()

  return (
    <Engineer
      jobId="job-1"
      drillDown={{
        signature: SELECTED_SIGNATURE,
        label: 'Selected Manager failure',
        attempt_ids: [],
        unit_ids: [],
      }}
      onClearDrillDown={() => {}}
      initialViewState={viewState}
      onViewStateChange={updateViewState}
      feedbackDrafts={{}}
      onFeedbackDraftsChange={() => {}}
    />
  )
}

describe('Engineer Manager drill-down rendering', () => {
  beforeEach(() => {
    apiMocks.units.mockReset().mockResolvedValue({ units: [], run_count: 0 })
    apiMocks.clusters.mockReset().mockResolvedValue({
      clusters: Array.from({ length: CLUSTER_COUNT }, (_, index) => cluster(index)),
    })
    apiMocks.feedback.mockReset().mockResolvedValue({ entries: [] })
    apiMocks.actions.mockReset().mockResolvedValue({ entries: [] })
  })

  test('settles without a parent-state render loop and leaves failure families collapsed', async () => {
    let renderCount = 0
    render(<EngineerStateHarness onRender={() => { renderCount += 1 }} />)

    await screen.findByRole('heading', { name: 'Failure families' })
    await waitFor(() => expect(screen.getByRole('button', { name: `Show ${CLUSTER_COUNT}` })).toBeTruthy())
    expect(screen.queryByRole('button', { name: 'Collapse' })).toBeNull()
    expect(screen.queryByText('Unique cluster detail 0')).toBeNull()

    await act(() => new Promise((resolve) => setTimeout(resolve, 25)))
    const settledRenderCount = renderCount
    await act(() => new Promise((resolve) => setTimeout(resolve, 50)))

    expect(renderCount).toBe(settledRenderCount)
  })
})
