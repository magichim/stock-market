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
  const [menuOpen, setMenuOpen] = useState(false)

  useEffect(() => {
    fetchMe()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setLoading(false))
    fetchEvents().then(setEvents, () => setEvents([]))
  }, [])

  // 사용자 드롭다운 — header-actions 밖을 누르면 닫힌다
  useEffect(() => {
    if (!menuOpen) return
    const close = (e: PointerEvent) => {
      if (!(e.target as Element).closest('.header-actions')) setMenuOpen(false)
    }
    document.addEventListener('pointerdown', close)
    return () => document.removeEventListener('pointerdown', close)
  }, [menuOpen])

  const handleLogout = async () => {
    setMenuOpen(false)
    await logout()
    setUser(null)
  }

  const name = user ? (user.display_name ?? user.username) : ''

  return (
    <div className="app">
      <header className="header">
        <div className="header-inner">
          <a className="logo" href="/">
            AGI<span className="logo-accent">SAJA</span>
            <span className="logo-sub">Stock</span>
          </a>
          <div className="header-actions">
            {loading ? null : user ? (
              <>
                {/* 사용자(아바타·이름)를 누르면 로그아웃 메뉴가 열린다 — PC·모바일 공통 */}
                <button className="header-user" aria-expanded={menuOpen} onClick={() => setMenuOpen((open) => !open)}>
                  <span className="header-avatar">
                    {user.avatar_url ? <img src={user.avatar_url} alt="" /> : name.slice(0, 1)}
                  </span>
                  <span className="header-user-name">{name}</span>
                </button>
                {menuOpen && (
                  <nav className="nav">
                    <button onClick={handleLogout}>로그아웃</button>
                  </nav>
                )}
              </>
            ) : (
              <a className="btn btn-primary" href={loginUrl()}>
                로그인
              </a>
            )}
          </div>
        </div>
      </header>

      <main className="main">
        <nav className="filter-tabs">
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
    </div>
  )
}
