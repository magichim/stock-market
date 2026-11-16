export const won = (n: number) => `${Math.round(n).toLocaleString('ko-KR')}원`

// 통화별 금액 — KRW는 원 단위, 그 외는 소수 2자리 + 통화 코드
export const money = (n: number, currency: string) =>
  currency === 'KRW'
    ? won(n)
    : `${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${currency}`

export const pct = (r: number) => `${r > 0 ? '+' : ''}${(r * 100).toFixed(2)}%`

// 상승 빨강 · 하락 파랑 (국내 관례)
export const trendClass = (n: number) => (n > 0 ? 'up' : n < 0 ? 'down' : '')
