import { apiFetch, apiUrl } from '@/lib/api'

export interface UsageTotals {
  total_tokens: number
  prompt_tokens: number
  completion_tokens: number
  total_calls: number
  cache_read_input_tokens: number
  cache_creation_input_tokens: number
  cache_input_tokens: number
  cache_reported_calls: number
  cache_hit_rate: number | null
  ttft_seconds: number | null
  tokens_per_second: number | null
  duration_seconds: number
  estimated_calls: number
}

export interface ModelUsage extends UsageTotals {
  provider: string
  model: string
}

export interface DailyUsage {
  date: string
  total_tokens: number
  total_calls: number
  turns: number
  tracked_turns: number
}

export interface UsageStatistics {
  year: number
  timezone: string
  totals: UsageTotals
  days: DailyUsage[]
  models: ModelUsage[]
  active_days: number
  sessions: number
  turns: number
  tracked_turns: number
  updated_at: number
}

export async function fetchUsageStatistics(
  year: number,
  signal?: AbortSignal
): Promise<UsageStatistics> {
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
  const query = new URLSearchParams({ year: String(year), timezone })
  const response = await apiFetch(apiUrl(`/api/settings/usage?${query}`), { signal })
  if (!response.ok) throw new Error(`Usage request failed (${response.status})`)
  return response.json()
}

export function usageYear(value: string | null, current: number): number {
  const year = Number(value)
  return Number.isInteger(year) && year >= 1970 && year <= current ? year : current
}

/** UTC calendar arithmetic avoids DST gaps; the API already bins in local time. */
export function activityCalendar(days: readonly DailyUsage[], year: number) {
  const byDate = new Map(days.map(day => [day.date, day]))
  const start = new Date(Date.UTC(year, 0, 1))
  const offset = (start.getUTCDay() + 6) % 7
  const dates: DailyUsage[] = []
  for (
    let day = new Date(start);
    day.getUTCFullYear() === year;
    day.setUTCDate(day.getUTCDate() + 1)
  ) {
    const date = day.toISOString().slice(0, 10)
    dates.push(
      byDate.get(date) ?? { date, total_tokens: 0, total_calls: 0, turns: 0, tracked_turns: 0 }
    )
  }
  const weeks: (DailyUsage | null)[][] = []
  for (let week = 0; week < Math.ceil((offset + dates.length) / 7); week++) {
    weeks.push(
      Array.from({ length: 7 }, (_, weekday) => dates[week * 7 + weekday - offset] ?? null)
    )
  }
  return { weeks, dates, offset }
}
