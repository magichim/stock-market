import { useCallback, useEffect, useState } from 'react'
import { fetchStocks, placeTrade, type Stock } from '../api'
import { money, pct, trendClass } from '../format'

// 종목 목록 + 시장가 매수·매도. 가격은 30초마다 다시 읽는다 (서버 수집 주기 기본 1시간)
export function StocksView({
  loggedIn,
  event,
  focus,
}: {
  loggedIn: boolean
  event?: string
  focus?: { symbol: string } | null
}) {
  const [stocks, setStocks] = useState<Stock[]>([])
  const [marketOpen, setMarketOpen] = useState(false)
  const [quantities, setQuantities] = useState<Record<string, number>>({})
  const [message, setMessage] = useState('')

  const load = useCallback(async () => {
    try {
      const data = await fetchStocks()
      setStocks(data.stocks)
      setMarketOpen(data.market_open)
    } catch (err) {
      setMessage(err instanceof Error ? err.message : '종목을 불러오지 못했습니다.')
    }
  }, [])

  useEffect(() => {
    load()
    const timer = setInterval(load, 30_000)
    return () => clearInterval(timer)
  }, [load])

  // 검색에서 고른 종목으로 스크롤 — 목록이 아직 없으면 불러온 뒤에
  const [focused, setFocused] = useState<string | null>(null)
  const loaded = stocks.length > 0
  useEffect(() => {
    if (!focus || !loaded) return
    document.getElementById(`stock-${focus.symbol}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    setFocused(focus.symbol)
    const timer = setTimeout(() => setFocused(null), 1600)
    return () => clearTimeout(timer)
  }, [focus, loaded])

  const trade = async (symbol: string, side: 'buy' | 'sell') => {
    const quantity = quantities[symbol] || 1
    try {
      const t = await placeTrade({ symbol, side, quantity, event })
      setMessage(`${t.name} ${t.quantity}주 ${side === 'buy' ? '매수' : '매도'} 체결 · ${money(t.price, t.currency)}`)
    } catch (err) {
      setMessage(err instanceof Error ? err.message : '주문에 실패했습니다.')
    }
  }

  return (
    <section className="panel">
      <p className="dim">{marketOpen ? '장 운영 중 · 주문은 최신가로 즉시 체결됩니다' : '장 마감 · 평일 09:00–15:30에 거래할 수 있습니다'}</p>
      {message && <p className="notice">{message}</p>}
      <ul className="stocks">
        {stocks.map((s) => {
          const change = s.price && s.prev_close ? s.price / s.prev_close - 1 : 0
          return (
            <li key={s.symbol} id={`stock-${s.symbol}`} className={s.symbol === focused ? 'stock focused' : 'stock'}>
              <div className="stock-info">
                <strong>{s.name}</strong>
                <div className="dim">
                  {s.symbol} · {s.market}
                </div>
              </div>
              <div className="stock-price num">
                {s.price === null ? '—' : money(s.price, s.currency)}
                <div className={trendClass(change)}>{pct(change)}</div>
              </div>
              {loggedIn && (
                <div className="order">
                  <input
                    type="number"
                    min={1}
                    value={quantities[s.symbol] ?? 1}
                    onChange={(e) => setQuantities({ ...quantities, [s.symbol]: Number(e.target.value) })}
                  />
                  <button className="btn btn-primary" disabled={!marketOpen} onClick={() => trade(s.symbol, 'buy')}>
                    매수
                  </button>
                  <button className="btn btn-outline" disabled={!marketOpen} onClick={() => trade(s.symbol, 'sell')}>
                    매도
                  </button>
                </div>
              )}
            </li>
          )
        })}
      </ul>
    </section>
  )
}
