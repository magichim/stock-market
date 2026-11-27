import { useEffect, useState } from 'react'
import { fetchIndices, type MarketIndex } from '../api'
import { pct, trendClass } from '../format'

const num = (n: number) => n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const signed = (n: number) => `${n > 0 ? '+' : ''}${num(n)}`

// 메인 — 주요 지수·환율 숫자 + 국내·해외 종목 화면 이동. 지수는 60초마다 다시 읽는다 (서버도 60초 캐시)
export function HomeView({ onMarket }: { onMarket: (domestic: boolean) => void }) {
  const [indices, setIndices] = useState<MarketIndex[] | null>(null)

  useEffect(() => {
    const load = () => fetchIndices().then(setIndices, () => {})
    load()
    const timer = setInterval(load, 60_000)
    return () => clearInterval(timer)
  }, [])

  return (
    <>
      {indices && (
        <section className="panel">
          <h2>주요 지수</h2>
          <ul className="indices">
            {indices.map((i) => {
              const diff = i.price !== null && i.prev_close ? i.price - i.prev_close : null
              return (
                <li key={i.name} className="index">
                  <div className="dim">{i.name}</div>
                  <strong className="num">{i.price === null ? '—' : num(i.price)}</strong>
                  <div className={`num ${diff === null ? 'dim' : trendClass(diff)}`}>
                    {diff === null ? '—' : `${signed(diff)} (${pct(diff / i.prev_close!)})`}
                  </div>
                </li>
              )
            })}
          </ul>
        </section>
      )}
      <nav className="market-nav">
        <button className="btn btn-outline" onClick={() => onMarket(true)}>
          국내주식
        </button>
        <button className="btn btn-outline" onClick={() => onMarket(false)}>
          해외주식
        </button>
      </nav>
    </>
  )
}
