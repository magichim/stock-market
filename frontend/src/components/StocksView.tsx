import { useCallback, useEffect, useState } from 'react'
import { fetchStocks, placeTrade, type MarketSession, type Stock } from '../api'
import { money, pct, trendClass } from '../format'
import { StockLogo } from './StockLogo'

// 매수·매도 일시 중단 — true로 바꾸면 다시 주문할 수 있다 (화면만 막는다. API는 그대로)
const TRADING_ENABLED = false

const SESSION_TEXT = {
  regular: '장 운영 중 · 주문은 최신가로 즉시 체결됩니다',
  nxt: 'NXT 거래 시간 · NXT에서 거래되는 종목만 주문할 수 있습니다',
  closed: '장 마감 · 평일 08:00–20:00에 거래할 수 있습니다 (NXT 미거래 종목은 09:00–15:30)',
}

// 국내(KRW) · 해외(그 외 통화) 탭 — URL(/domestic, /overseas)은 App이 관리한다
const MARKETS = [
  { label: '국내주식', domestic: true },
  { label: '해외주식', domestic: false },
]

// 종목 구분 필터
type Kind = 'all' | Stock['kind']
const KINDS: { key: Kind; label: string }[] = [
  { key: 'all', label: '전체' },
  { key: 'stock', label: '단일' },
  { key: 'etf', label: 'ETF' },
]

// 국내(/api/stocks/domestic) 또는 해외(/api/stocks/overseas) 종목 목록 + 시장가 매수·매도. 가격은 30초마다 다시 읽는다 (서버 수집 주기 기본 1시간)
export function StocksView({
  domestic,
  onMarket,
  loggedIn,
  event,
  focus,
}: {
  domestic: boolean
  onMarket: (domestic: boolean) => void
  loggedIn: boolean
  event?: string
  focus?: { symbol: string } | null
}) {
  const [stocks, setStocks] = useState<Stock[]>([])
  const [loaded, setLoaded] = useState(false)
  const [session, setSession] = useState<MarketSession>(null)
  const [quantities, setQuantities] = useState<Record<string, number>>({})
  const [message, setMessage] = useState('')
  const [kind, setKind] = useState<Kind>('all')
  // 검색으로 종목을 고르면 필터를 전체로 — 스크롤 effect보다 먼저 반영되도록 렌더 중에 바꾼다
  const [prevFocus, setPrevFocus] = useState(focus)
  if (focus !== prevFocus) {
    setPrevFocus(focus)
    setKind('all')
  }
  // 진행 중인 주문 — 끝날 때까지 모든 주문 버튼을 막고, 누른 버튼은 '매수 중'처럼 표시한다
  const [pending, setPending] = useState<{ symbol: string; side: 'buy' | 'sell' } | null>(null)

  const load = useCallback(async () => {
    try {
      const data = await fetchStocks(domestic)
      setStocks(data.stocks)
      setSession(data.session)
      setLoaded(true)
    } catch (err) {
      setMessage(err instanceof Error ? err.message : '종목을 불러오지 못했습니다.')
    }
  }, [domestic])

  useEffect(() => {
    load()
    const timer = setInterval(load, 30_000)
    return () => clearInterval(timer)
  }, [load])

  // 검색에서 고른 종목으로 스크롤 — 목록이 아직 없으면 불러온 뒤에
  const [focused, setFocused] = useState<string | null>(null)
  useEffect(() => {
    if (!focus || !loaded) return
    document.getElementById(`stock-${focus.symbol}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    setFocused(focus.symbol)
    const timer = setTimeout(() => setFocused(null), 1600)
    return () => clearTimeout(timer)
  }, [focus, loaded])

  const trade = async (symbol: string, side: 'buy' | 'sell') => {
    const quantity = quantities[symbol] || 1
    setPending({ symbol, side })
    try {
      const t = await placeTrade({ symbol, side, quantity, event })
      setMessage(`${t.name} ${t.quantity}주 ${side === 'buy' ? '매수' : '매도'} 체결 · ${money(t.price, t.currency)}`)
    } catch (err) {
      setMessage(err instanceof Error ? err.message : '주문에 실패했습니다.')
    } finally {
      setPending(null)
    }
  }
  const sideLabel = (symbol: string, side: 'buy' | 'sell') =>
    `${side === 'buy' ? '매수' : '매도'}${pending?.symbol === symbol && pending.side === side ? ' 중' : ''}`

  const list = stocks.filter((s) => kind === 'all' || s.kind === kind)

  // 종목 한 줄
  const stockRow = (s: Stock) => {
    const change = s.price && s.close_price ? s.price / s.close_price - 1 : null
    return (
      <li key={s.symbol} id={`stock-${s.symbol}`} className={s.symbol === focused ? 'stock focused' : 'stock'}>
        <StockLogo symbol={s.symbol} name={s.name} size={40} />
        <div className="stock-info">
          <strong>{s.name}</strong>
          <div className="dim">
            {s.symbol} · {s.market}
          </div>
        </div>
        <div className="stock-close num">
          {s.close_price === null ? '—' : money(s.close_price, s.currency)}
          <div className="dim">전일 종가</div>
        </div>
        <div className="stock-price num">
          {s.price === null ? '—' : money(s.price, s.currency)}
          <div className={change === null ? 'dim' : trendClass(change)}>{change === null ? '—' : pct(change)}</div>
        </div>
        {loggedIn && (
          <div className="order">
            <input
              disabled={!TRADING_ENABLED}
              type="number"
              min={1}
              value={quantities[s.symbol] ?? 1}
              onChange={(e) => setQuantities({ ...quantities, [s.symbol]: Number(e.target.value) })}
            />
            <button className="btn btn-primary" disabled={!TRADING_ENABLED || !s.tradable || !!pending} onClick={() => trade(s.symbol, 'buy')}>
              {sideLabel(s.symbol, 'buy')}
            </button>
            <button className="btn btn-outline" disabled={!TRADING_ENABLED || !s.tradable || !!pending} onClick={() => trade(s.symbol, 'sell')}>
              {sideLabel(s.symbol, 'sell')}
            </button>
          </div>
        )}
      </li>
    )
  }

  return (
    <section className="panel">
      <p className="dim">{TRADING_ENABLED ? SESSION_TEXT[session ?? 'closed'] : '매수·매도는 잠시 중단되었습니다'}</p>
      {message && <p className="notice">{message}</p>}
      <nav className="filter-tabs">
        {MARKETS.map((m) => (
          <button key={m.label} className={m.domestic === domestic ? 'active' : ''} onClick={() => onMarket(m.domestic)}>
            {m.label}
          </button>
        ))}
      </nav>
      <div className="kind-filter">
        {KINDS.map((k) => (
          <button key={k.key} className={k.key === kind ? 'active' : ''} onClick={() => setKind(k.key)}>
            {k.label}
          </button>
        ))}
      </div>
      {loaded && list.length === 0 ? <p className="dim">종목이 없습니다.</p> : <ul className="stocks">{list.map(stockRow)}</ul>}
    </section>
  )
}
