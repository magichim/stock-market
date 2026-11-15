export const won = (n: number) => `${Math.round(n).toLocaleString('ko-KR')}원`

export const pct = (r: number) => `${r > 0 ? '+' : ''}${(r * 100).toFixed(2)}%`

// 상승 빨강 · 하락 파랑 (국내 관례)
export const trendClass = (n: number) => (n > 0 ? 'up' : n < 0 ? 'down' : '')
