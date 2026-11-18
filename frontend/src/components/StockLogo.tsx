import { useState } from 'react'

// 종목 로고 — public/logos/{symbol}.svg, 파일이 없으면 종목명 첫 글자로 대신한다
export function StockLogo({ symbol, name, size = 36 }: { symbol: string; name: string; size?: number }) {
  const [missing, setMissing] = useState(false)
  const style = { width: size, height: size }
  if (missing)
    return (
      <span className="stock-logo stock-logo-fallback" style={{ ...style, fontSize: size * 0.42 }} aria-hidden>
        {name.charAt(0)}
      </span>
    )
  return <img className="stock-logo" src={`/logos/${symbol}.svg`} alt="" style={style} onError={() => setMissing(true)} />
}
