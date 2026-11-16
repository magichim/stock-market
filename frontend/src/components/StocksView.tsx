import { useCallback, useEffect, useState } from 'react'
import { fetchStocks, placeTrade, type Stock } from '../api'
import { pct, trendClass, won } from '../format'

// 종목 목록 + 시장가 매수·매도. 가격은 30초마다 다시 읽는다 (서버 수집 주기 기본 60초)
export function StocksView({ loggedIn, event }: { loggedIn: boolean; event?: string }) {
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

  const trade = async (symbol: string, side: 'buy' | 'sell') => {
    const quantity = quantities[symbol] || 1
    try {
      const t = await placeTrade({ symbol, side, quantity, event })
      setMessage(`${t.name} ${t.quantity}주 ${side === 'buy' ? '매수' : '매도'} 체결 · ${won(t.price)}`)
    } catch (err) {
      setMessage(err instanceof Error ? err.message : '주문에 실패했습니다.')
    }
  }

  return (
    <section className="panel">
      <p className="dim">{marketOpen ? '장 운영 중 · 주문은 최신가로 즉시 체결됩니다' : '장 마감 · 평일 09:00–15:30에 거래할 수 있습니다'}</p>
      {message && <p className="notice">{message}</p>}
      <table className="stocks">
        <tbody>
          {stocks.map((s) => {
            const change = s.price && s.prev_close ? s.price / s.prev_close - 1 : 0
            return (
              <tr key={s.symbol}>
                <td>
                  <strong>{s.name}</strong>
                  <div className="dim">
                    {s.symbol} · {s.market}
                  </div>
                </td>
                <td className="num">
                  {s.price === null ? '—' : won(s.price)}
                  <div className={trendClass(change)}>{pct(change)}</div>
                </td>
                {loggedIn && (
                  <td className="order">
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
                  </td>
                )}
              </tr>
            )
          })}
        </tbody>
      </table>
    </section>
  )
}
