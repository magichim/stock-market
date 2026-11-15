import { useEffect, useState } from 'react'
import { fetchAccount, fetchTrades, type Account, type Trade } from '../api'
import { pct, trendClass, won } from '../format'

// 내 계좌 — 평가액·수익률, 보유 종목, 최근 체결
export function AccountView({ event }: { event?: string }) {
  const [account, setAccount] = useState<Account | null>(null)
  const [trades, setTrades] = useState<Trade[]>([])
  const [error, setError] = useState('')

  useEffect(() => {
    Promise.all([fetchAccount(event), fetchTrades(event)])
      .then(([a, t]) => {
        setAccount(a)
        setTrades(t)
      })
      .catch((err) => setError(err instanceof Error ? err.message : '계좌를 불러오지 못했습니다.'))
  }, [event])

  if (error) return <p className="error">{error}</p>
  if (!account) return <p className="dim">불러오는 중…</p>

  return (
    <>
      <section className="card summary">
        <div>
          <span className="dim">총 평가액</span>
          <strong>{won(account.total_value)}</strong>
        </div>
        <div>
          <span className="dim">수익률</span>
          <strong className={trendClass(account.return_rate)}>{pct(account.return_rate)}</strong>
        </div>
        <div>
          <span className="dim">현금</span>
          <strong>{won(account.cash)}</strong>
        </div>
      </section>

      <section className="card">
        <h2>보유 종목</h2>
        {account.holdings.length === 0 ? (
          <p className="dim">보유 종목이 없습니다.</p>
        ) : (
          <table className="holdings">
            <thead>
              <tr>
                <th>종목</th>
                <th className="num">수량</th>
                <th className="num">평단</th>
                <th className="num">평가손익</th>
              </tr>
            </thead>
            <tbody>
              {account.holdings.map((h) => (
                <tr key={h.symbol}>
                  <td>{h.name}</td>
                  <td className="num">{h.quantity.toLocaleString('ko-KR')}</td>
                  <td className="num">{won(h.avg_price)}</td>
                  <td className={`num ${trendClass(h.pnl)}`}>{won(h.pnl)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="card">
        <h2>최근 체결</h2>
        {trades.length === 0 ? (
          <p className="dim">체결 내역이 없습니다.</p>
        ) : (
          <ul className="trades">
            {trades.map((t) => (
              <li key={t.id}>
                <span className={t.side === 'buy' ? 'up' : 'down'}>{t.side === 'buy' ? '매수' : '매도'}</span>
                {t.name} {t.quantity}주 · {won(t.price)}
                {t.realized_pnl !== null && <span className={trendClass(t.realized_pnl)}> · 실현 {won(t.realized_pnl)}</span>}
                <span className="dim"> · {new Date(t.executed_at).toLocaleString('ko-KR')}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  )
}
