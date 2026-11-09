// 로그인·refresh·로그아웃은 agisaja.com이 처리한다 (AUTH.md). 이 앱은 공유된 access 쿠키로 자기 API만 호출한다
export const AUTH_ORIGIN = import.meta.env.VITE_AUTH_ORIGIN || 'https://agisaja.com'

export interface User {
  id: number
  username: string
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

// 로그인은 agisaja.com 로그인 페이지에서 하고 ?next=로 이 페이지에 돌아온다
export const loginUrl = () => `${AUTH_ORIGIN}/login?next=${encodeURIComponent(window.location.href)}`

// agisaja.com에서 로그아웃해야 refresh 토큰까지 폐기되고 두 도메인이 함께 로그아웃된다
export async function logout(): Promise<void> {
  await fetch(`${AUTH_ORIGIN}/api/auth/logout`, { method: 'POST', credentials: 'include' })
}
