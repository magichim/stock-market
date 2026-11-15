import { useEffect, useState } from 'react'
import { fetchEvents, fetchMe, loginUrl, logout, type StockEvent, type User } from './api'
import { AccountView } from './components/AccountView'
import { LeaderboardView } from './components/LeaderboardView'
import { StocksView } from './components/StocksView'

type Tab = 'stocks' | 'account' | 'leaderboard'
const TABS: { key: Tab; label: string }[] = [
  { key: 'stocks', label: '종목' },
  { key: 'account', label: '내 계좌' },
  { key: 'leaderboard', label: '리더보드' },
]

export function App() {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState<Tab>('stocks')
  const [events, setEvents] = useState<StockEvent[]>([])
  // 거래할 계좌 — 빈 값이면 기본 계좌, 아니면 이벤트 slug
  const [event, setEvent] = useState('')

  useEffect(() => {
    fetchMe()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setLoading(false))
    fetchEvents().then(setEvents, () => setEvents([]))
  }, [])

  const handleLogout = async () => {
    await logout()
    setUser(null)
  }

  return (
    <main className="page">
      <header className="topbar">
        <h1>AGISAJA Stock</h1>
        {loading ? null : user ? (
          <div className="me">
            <span>{user.display_name ?? user.username}</span>
            <button className="secondary" onClick={handleLogout}>
              로그아웃
            </button>
          </div>
        ) : (
          <a className="button" href={loginUrl()}>
            로그인
          </a>
        )}
      </header>

      <nav className="tabs">
        {TABS.map((t) => (
          <button key={t.key} className={t.key === tab ? 'active' : ''} onClick={() => setTab(t.key)}>
            {t.label}
          </button>
        ))}
        {user && events.length > 0 && tab !== 'leaderboard' && (
          <select value={event} onChange={(e) => setEvent(e.target.value)}>
            <option value="">기본 계좌</option>
            {events.map((e) => (
              <option key={e.slug} value={e.slug}>
                {e.title}
              </option>
            ))}
          </select>
        )}
      </nav>

      {tab === 'stocks' && <StocksView loggedIn={!!user} event={event || undefined} />}
      {tab === 'account' &&
        (user ? <AccountView event={event || undefined} /> : <p className="dim">로그인하면 내 계좌를 볼 수 있습니다.</p>)}
      {tab === 'leaderboard' && <LeaderboardView events={events} />}
    </main>
  )
}
