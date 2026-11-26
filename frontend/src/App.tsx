import { useEffect, useState } from 'react'
import { fetchEvents, fetchMe, loginUrl, logout, type StockEvent, type StockHit, type User } from './api'
import { AccountView } from './components/AccountView'
import { LeaderboardView } from './components/LeaderboardView'
import { StockSearch } from './components/StockSearch'
import { StocksView } from './components/StocksView'

// 화면 — 종목은 국내·해외를 URL로 나눈다
type Tab = 'domestic' | 'overseas' | 'account' | 'leaderboard'
const PATHS: Record<Tab, string> = {
  domestic: '/domestic',
  overseas: '/overseas',
  account: '/account',
  leaderboard: '/leaderboard',
}
// 헤더 메뉴 — '종목'은 국내·해외 화면을 함께 가리킨다
const TABS: { key: Tab; label: string }[] = [
  { key: 'domestic', label: '종목' },
  { key: 'account', label: '내 계좌' },
  { key: 'leaderboard', label: '리더보드' },
]
const menuKey = (tab: Tab) => (tab === 'overseas' ? 'domestic' : tab)
// URL 경로 → 화면. 모르는 경로(/ 포함)는 국내 종목 (서버는 모든 경로에 index.html을 준다)
const tabFromPath = () =>
  (Object.keys(PATHS) as Tab[]).find((t) => PATHS[t] === window.location.pathname) ?? 'domestic'

export function App() {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState<Tab>(tabFromPath)
  const [events, setEvents] = useState<StockEvent[]>([])
  // 거래할 계좌 — 빈 값이면 기본 계좌, 아니면 이벤트 slug
  const [event, setEvent] = useState('')
  const [menuOpen, setMenuOpen] = useState(false)
  // 검색에서 고른 종목 — 매번 새 객체라 같은 종목을 다시 골라도 이동한다
  const [focus, setFocus] = useState<{ symbol: string } | null>(null)

  useEffect(() => {
    fetchMe()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setLoading(false))
    fetchEvents().then(setEvents, () => setEvents([]))
    // 뒤로·앞으로 가기
    const onPop = () => setTab(tabFromPath())
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
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
  // 화면 이동 — 다른 화면이면 URL도 바꾼다
  const go = (next: Tab) => {
    if (PATHS[next] !== window.location.pathname) window.history.pushState(null, '', PATHS[next])
    setTab(next)
  }
  const tabButtons = TABS.map((t) => (
    <button
      key={t.key}
      className={t.key === menuKey(tab) ? 'active' : ''}
      onClick={() => {
        if (t.key !== menuKey(tab)) go(t.key)
        setMenuOpen(false)
      }}
    >
      {t.label}
    </button>
  ))
  const toggleMenu = () => setMenuOpen((open) => !open)

  // 검색 결과 선택 — 국내(KRW)·해외 종목 화면으로 가서 그 종목으로 스크롤
  const goToStock = (hit: StockHit) => {
    go(hit.currency === 'KRW' ? 'domestic' : 'overseas')
    setFocus({ symbol: hit.symbol })
  }

  return (
    <div className="app">
      <header className="header">
        <div className="header-inner">
          <a className="logo" href="/">
            AGI<span className="logo-accent">SAJA</span>
            <span className="logo-sub">Stock</span>
          </a>
          <nav className="nav">{tabButtons}</nav>
          <StockSearch onSelect={goToStock} />
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

        {(tab === 'domestic' || tab === 'overseas') && (
          <StocksView
            key={tab}
            domestic={tab === 'domestic'}
            onMarket={(domestic) => go(domestic ? 'domestic' : 'overseas')}
            loggedIn={!!user}
            event={event || undefined}
            focus={focus}
          />
        )}
        {tab === 'account' &&
          (user ? <AccountView event={event || undefined} /> : <p className="dim">로그인하면 내 계좌를 볼 수 있습니다.</p>)}
        {tab === 'leaderboard' && <LeaderboardView events={events} />}
      </main>
    </div>
  )
}
