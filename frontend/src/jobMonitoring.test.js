import assert from 'node:assert/strict'
import test from 'node:test'
import { monitorJob } from './jobMonitoring.js'

const noWait = async () => {}

test('recovers from a transient status failure without creating another job', async () => {
  const responses = [new Error('network unavailable'), { status: 'running' }, { status: 'done' }]
  const statuses = []
  const reconnects = []
  let statusCalls = 0

  const result = await monitorJob({
    jobId: 'job-1',
    getStatus: async (jobId) => {
      assert.equal(jobId, 'job-1')
      statusCalls += 1
      const response = responses.shift()
      if (response instanceof Error) throw response
      return response
    },
    isCurrent: () => true,
    onStatus: (status) => statuses.push(status.status),
    onReconnect: (state) => reconnects.push(state.attempt),
    sleep: noWait,
  })

  assert.equal(statusCalls, 3)
  assert.deepEqual(statuses, ['running', 'done'])
  assert.deepEqual(reconnects, [1])
  assert.equal(result.kind, 'done')
})

test('pauses monitoring after bounded consecutive failures', async () => {
  let statusCalls = 0
  const result = await monitorJob({
    jobId: 'job-1',
    getStatus: async () => {
      statusCalls += 1
      throw new Error('service unavailable')
    },
    isCurrent: () => true,
    onStatus: () => assert.fail('No status should be emitted'),
    sleep: noWait,
  })

  assert.equal(statusCalls, 3)
  assert.equal(result.kind, 'paused')
  assert.equal(result.error.message, 'service unavailable')
})

test('ignores late status responses after a newer run starts', async () => {
  let current = true
  const result = await monitorJob({
    jobId: 'job-1',
    getStatus: async () => {
      current = false
      return { status: 'done' }
    },
    isCurrent: () => current,
    onStatus: () => assert.fail('A stale status should not be emitted'),
    sleep: noWait,
  })

  assert.equal(result.kind, 'stale')
})