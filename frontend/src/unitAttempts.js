export function groupAttempts(group) {
  const attempts = [group.final, ...(group.failures || [])].filter(Boolean)
  return Array.from(
    new Map(attempts.map((attempt) => [attempt.unit_id, attempt])).values(),
  )
}