// 종목 로고 — src/assets/stock-logo/{symbol}.svg. 빌드하면 dist/assets에 파일로 나간다 (vite.config.ts assetsInlineLimit)
const LOGOS = import.meta.glob<string>('../assets/stock-logo/*.svg', { eager: true, import: 'default' })

// 로고가 없으면 종목명 첫 글자로 대신한다
export function StockLogo({ symbol, name, size = 36 }: { symbol: string; name: string; size?: number }) {
  const src = LOGOS[`../assets/stock-logo/${symbol}.svg`]
  const style = { width: size, height: size }
  if (!src)
    return (
      <span className="stock-logo stock-logo-fallback" style={{ ...style, fontSize: size * 0.42 }} aria-hidden>
        {name.charAt(0)}
      </span>
    )
  return <img className="stock-logo" src={src} alt="" style={style} />
}
