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
  // 탭 메뉴 — PC는 헤더 네비게이션, 768px 이하는 오른쪽 드롭다운 안에 같은 버튼을 둔다
  const tabButtons = TABS.map((t) => (
    <button
      key={t.key}
      className={t.key === tab ? 'active' : ''}
      onClick={() => {
        setTab(t.key)
        setMenuOpen(false)
      }}
    >
      {t.label}
    </button>
  ))
  const toggleMenu = () => setMenuOpen((open) => !open)

  return (
    <div className="app">
      <header className="header">
        <div className="header-inner">
          <a className="logo" href="/">
            AGI<span className="logo-accent">SAJA</span>
            <span className="logo-sub">Stock</span>
          </a>
          <nav className="nav">{tabButtons}</nav>
          <div className="header-actions">
            {loading ? null : (
              <>
                {user ? (
                  // 사용자(아바타·이름)를 누르면 드롭다운이 열린다 — PC는 로그아웃, 모바일은 탭 + 로그아웃
                  <button className="header-user" aria-expanded={menuOpen} onClick={toggleMenu}>
                    <span className="header-avatar">
                      {user.avatar_url ? <img src={user.avatar_url} alt="" /> : name.slice(0, 1)}
                    </span>
                    <span className="header-user-name">{name}</span>
                  </button>
                ) : (
                  <>
                    <a className="btn btn-primary" href={loginUrl()}>
                      로그인
                    </a>
                    {/* 비로그인 모바일 — 탭을 열 메뉴 버튼 (PC에서는 숨김) */}
                    <button className="menu-toggle" aria-label="메뉴" aria-expanded={menuOpen} onClick={toggleMenu}>
                      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
                        <path d="M4 6h16M4 12h16M4 18h16" />
                      </svg>
                    </button>
                  </>
                )}
                {menuOpen && (
                  <div className="menu">
                    <div className="menu-tabs">{tabButtons}</div>
                    {user && <button onClick={handleLogout}>로그아웃</button>}
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </header>

      <main className="main">
        {user && events.length > 0 && tab !== 'leaderboard' && (
          <div className="account-select">
            <select value={event} onChange={(e) => setEvent(e.target.value)}>
              <option value="">기본 계좌</option>
              {events.map((e) => (
                <option key={e.slug} value={e.slug}>
                  {e.title}
                </option>
              ))}
            </select>
          </div>
        )}

        {tab === 'stocks' && <StocksView loggedIn={!!user} event={event || undefined} />}
        {tab === 'account' &&
          (user ? <AccountView event={event || undefined} /> : <p className="dim">로그인하면 내 계좌를 볼 수 있습니다.</p>)}
        {tab === 'leaderboard' && <LeaderboardView events={events} />}
      </main>
    </div>
  )
}
