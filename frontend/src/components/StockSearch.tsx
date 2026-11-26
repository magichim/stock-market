import { useEffect, useRef, useState } from 'react'
import { searchStocks, type StockHit } from '../api'
import { money } from '../format'
import { StockLogo } from './StockLogo'

const DEBOUNCE_MS = 250

// 헤더 종목 검색 — 입력이 멈추면 검색 API를 호출하고, 결과를 입력창 아래 목록으로 보여준다
export function StockSearch({ onSelect }: { onSelect: (hit: StockHit) => void }) {
  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<StockHit[]>([])
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const boxRef = useRef<HTMLDivElement>(null)

  // 디바운스 — 입력이 바뀌면 이전 타이머·요청을 취소하고 다시 기다린다
  useEffect(() => {
    const q = query.trim()
    if (!q) {
      setHits([])
      return
    }
    const ctrl = new AbortController()
    const timer = setTimeout(() => {
      searchStocks(q, ctrl.signal)
        .then((r) => {
          setHits(r)
          setActive(0)
        })
        .catch(() => {}) // 취소·실패는 이전 결과를 유지
    }, DEBOUNCE_MS)
    return () => {
      clearTimeout(timer)
      ctrl.abort()
    }
  }, [query])

  // 바깥을 누르면 목록을 닫는다
  useEffect(() => {
    if (!open) return
    const close = (e: PointerEvent) => {
      if (!boxRef.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', close)
    return () => document.removeEventListener('pointerdown', close)
  }, [open])

  const select = (hit: StockHit) => {
    onSelect(hit)
    setQuery('')
    setHits([])
    setOpen(false)
  }

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      const step = e.key === 'ArrowDown' ? 1 : -1
      setActive((i) => (i + step + hits.length) % Math.max(hits.length, 1))
    } else if (e.key === 'Enter' && hits[active]) {
      select(hits[active])
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  return (
    <div className="search" ref={boxRef}>
      <input
        type="search"
        placeholder="종목명·코드 검색"
        value={query}
        onChange={(e) => {
          setQuery(e.target.value)
          setOpen(true)
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
      />
      {open && query.trim() && (
        <ul className="search-results">
          {hits.length === 0 ? (
            <li className="search-empty">검색 결과가 없습니다.</li>
          ) : (
            hits.map((h, i) => (
              <li key={h.symbol}>
                <button
                  className={i === active ? 'active' : ''}
                  onMouseEnter={() => setActive(i)}
                  onClick={() => select(h)}
                >
                  <StockLogo symbol={h.symbol} name={h.name} size={32} />
                  <span className="search-name">
                    <strong>{h.name}</strong>
                    <span className="dim">
                      {h.symbol} · {h.market}
                    </span>
                  </span>
                  <span className="num">{h.price === null ? '—' : money(h.price, h.currency)}</span>
                </button>
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  )
}
