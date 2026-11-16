// 로그인·refresh·로그아웃은 agisaja.com이 처리한다 (AUTH.md). 이 앱은 공유된 access 쿠키로 자기 API만 호출한다
export const AUTH_ORIGIN = import.meta.env.VITE_AUTH_ORIGIN || 'https://agisaja.com'

// display_name·avatar_url은 predict-market 프로필 — 조회에 실패하면 null
export interface User {
  id: number
  username: string
  display_name: string | null
  avatar_url: string | null
}

// has_session 표시 쿠키(.agisaja.com)로 로그인 여부만 안다 — 토큰 쿠키는 HttpOnly라 읽을 수 없다
export const hasSession = () => document.cookie.split('; ').some((c) => c.startsWith('has_session='))

// access 만료 시 agisaja.com에서 재발급 — 동시에 여러 요청이 401을 받아도 refresh는 한 번만
let refreshing: Promise<boolean> | null = null
function refreshSession(): Promise<boolean> {
  refreshing ??= fetch(`${AUTH_ORIGIN}/api/auth/refresh`, { method: 'POST', credentials: 'include' })
    .then((res) => res.ok)
    .catch(() => false)
    .finally(() => {
      refreshing = null
    })
  return refreshing
}

// 401이면 refresh 후 한 번 더 보낸다. refresh가 실패하면 agisaja.com이 세션 쿠키를 지우므로 재시도는 비로그인으로 처리된다
async function send(path: string, init?: RequestInit): Promise<Response> {
  const res = await fetch(path, init)
  if (res.status !== 401 || !hasSession()) return res
  await refreshSession()
  return fetch(path, init)
}

export async function fetchMe(): Promise<User | null> {
  const res = await send('/api/me')
  if (!res.ok) throw new Error(`/api/me ${res.status}`)
  return (await res.json()).user
}

export interface Stock {
  symbol: string
  name: string
  market: string
  currency: string
  price: number | null
  prev_close: number | null
  price_at: string | null
}

// 가격·평가액·손익은 종목 통화, value_krw만 KRW 환산
export interface Holding {
  symbol: string
  name: string
  currency: string
  quantity: number
  avg_price: number
  price: number
  value: number
  pnl: number
  value_krw: number
}

// 통화별 현금 — value는 KRW 환산 (rate = 1단위당 KRW)
export interface Balance {
  currency: string
  amount: number
  rate: number
  value: number
}

export interface Account {
  event: string | null
  initial_cash: number
  balances: Balance[]
  holdings: Holding[]
  total_value: number
  return_rate: number
}

export interface Trade {
  id: number
  symbol: string
  name: string
  currency: string
  side: 'buy' | 'sell'
  quantity: number
  price: number
  amount: number
  realized_pnl: number | null
  executed_at: string
}

export interface StockEvent {
  slug: string
  title: string
  description: string
  initial_cash: number
  start_date: string
  end_date: string
}

// 프로필 조회가 실패하면 username·display_name이 null로 온다 (순위는 유지)
export interface RankEntry {
  username: string | null
  display_name: string | null
  avatar_url: string | null
  return_rate: number
}

// 실패 응답의 detail(서버 한글 메시지)을 에러로 올린다
async function json<T>(res: Response): Promise<T> {
  if (res.ok) return res.json()
  const detail = await res.json().then((b) => b.detail, () => null)
  throw new Error(typeof detail === 'string' ? detail : `요청 실패 (${res.status})`)
}

const eventQuery = (event?: string) => (event ? `?event=${encodeURIComponent(event)}` : '')

export const fetchStocks = async () => json<{ market_open: boolean; stocks: Stock[] }>(await send('/api/stocks'))
export const fetchEvents = async () => json<StockEvent[]>(await send('/api/events'))
export const fetchAccount = async (event?: string) => json<Account>(await send(`/api/account${eventQuery(event)}`))
export const fetchTrades = async (event?: string) => json<Trade[]>(await send(`/api/account/trades${eventQuery(event)}`))
export const fetchLeaderboard = async (query: string) => json<RankEntry[]>(await send(`/api/leaderboard?${query}`))

// 시장가 주문 — 최신가로 즉시 전량 체결된다
export async function placeTrade(body: { symbol: string; side: 'buy' | 'sell'; quantity: number; event?: string }) {
  return json<Trade>(
    await send('/api/trades', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  )
}

// 로그인은 agisaja.com 로그인 페이지에서 하고 ?next=로 이 페이지에 돌아온다
export const loginUrl = () => `${AUTH_ORIGIN}/login?next=${encodeURIComponent(window.location.href)}`

// agisaja.com에서 로그아웃해야 refresh 토큰까지 폐기되고 두 도메인이 함께 로그아웃된다
export async function logout(): Promise<void> {
  await fetch(`${AUTH_ORIGIN}/api/auth/logout`, { method: 'POST', credentials: 'include' })
}
