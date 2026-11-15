import { useEffect, useState } from 'react'
import { fetchLeaderboard, type RankEntry, type StockEvent } from '../api'
import { pct, trendClass } from '../format'

const PERIODS = [
  { key: 'period=realtime', label: '실시간' },
  { key: 'period=month', label: '월간' },
  { key: 'period=year', label: '연간' },
]

// 수익률 리더보드 — 실시간(누적) · 이번 달 · 올해 · 이벤트
export function LeaderboardView({ events }: { events: StockEvent[] }) {
  const tabs = [...PERIODS, ...events.map((e) => ({ key: `event=${encodeURIComponent(e.slug)}`, label: e.title }))]
  const [query, setQuery] = useState(PERIODS[0].key)
  const [rows, setRows] = useState<RankEntry[]>([])
  const [error, setError] = useState('')

  useEffect(() => {
    setError('')
    fetchLeaderboard(query)
      .then(setRows)
      .catch((err) => setError(err instanceof Error ? err.message : '순위를 불러오지 못했습니다.'))
  }, [query])

  return (
    <section className="card">
      <div className="chips">
        {tabs.map((t) => (
          <button key={t.key} className={t.key === query ? '' : 'secondary'} onClick={() => setQuery(t.key)}>
            {t.label}
          </button>
        ))}
      </div>
      {error && <p className="error">{error}</p>}
      {rows.length === 0 ? (
        <p className="dim">아직 순위가 없습니다.</p>
      ) : (
        <ol className="ranking">
          {rows.map((r, i) => (
            <li key={i}>
              <span className="rank">{i + 1}</span>
              <span className="name">{r.display_name ?? r.username ?? '—'}</span>
              <span className={trendClass(r.return_rate)}>{pct(r.return_rate)}</span>
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}
