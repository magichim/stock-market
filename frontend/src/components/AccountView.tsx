import { useEffect, useState } from 'react'
import { fetchAccount, fetchTrades, type Account, type Trade } from '../api'
import { money, pct, trendClass, won } from '../format'
import { StockLogo } from './StockLogo'

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
  if (!account) return null

  return (
    <>
      <section className="panel summary">
        <div>
          <span className="dim">총 평가액</span>
          <strong>{won(account.total_value)}</strong>
        </div>
        <div>
          <span className="dim">수익률</span>
          <strong className={trendClass(account.return_rate)}>{pct(account.return_rate)}</strong>
        </div>
        {account.balances.map((b) => (
          <div key={b.currency}>
            <span className="dim">현금 {b.currency}</span>
            <strong>{money(b.amount, b.currency)}</strong>
          </div>
        ))}
      </section>

      <section className="panel">
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
                  <td>
                    <span className="holding-name">
                      <StockLogo symbol={h.symbol} name={h.name} size={28} />
                      {h.name}
                    </span>
                  </td>
                  <td className="num">{h.quantity.toLocaleString('ko-KR')}</td>
                  <td className="num">{money(h.avg_price, h.currency)}</td>
                  <td className={`num ${trendClass(h.pnl)}`}>{money(h.pnl, h.currency)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="panel">
        <h2>최근 체결</h2>
        {trades.length === 0 ? (
          <p className="dim">체결 내역이 없습니다.</p>
        ) : (
          <ul className="trades">
            {trades.map((t) => (
              <li key={t.id}>
                <span className={t.side === 'buy' ? 'up' : 'down'}>{t.side === 'buy' ? '매수' : '매도'}</span>
                {t.name} {t.quantity}주 · {money(t.price, t.currency)}
                {t.realized_pnl !== null && (
                  <span className={trendClass(t.realized_pnl)}> · 실현 {money(t.realized_pnl, t.currency)}</span>
                )}
                <span className="dim"> · {new Date(t.executed_at).toLocaleString('ko-KR')}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  )
}
