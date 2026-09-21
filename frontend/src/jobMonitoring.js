export async function monitorJob({
  jobId,
  getStatus,
  isCurrent,
  onStatus,
  onReconnect,
  sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds)),
  intervalMs = 700,
  maxConsecutiveErrors = 3,
}) {
  let consecutiveErrors = 0

  while (isCurrent()) {
    let status
    try {
      status = await getStatus(jobId)
      consecutiveErrors = 0
    } catch (error) {
      if (!isCurrent()) return { kind: 'stale' }
      consecutiveErrors += 1
      if (consecutiveErrors >= maxConsecutiveErrors) {
        return { kind: 'paused', error }
      }
      onReconnect?.({ attempt: consecutiveErrors, maxAttempts: maxConsecutiveErrors, error })
      await sleep(intervalMs)
      continue
    }

    if (!isCurrent()) return { kind: 'stale' }
    onStatus(status)
    if (['done', 'error', 'cancelled'].includes(status.status)) {
      return { kind: status.status, status }
    }
    await sleep(intervalMs)
  }

  return { kind: 'stale' }
}