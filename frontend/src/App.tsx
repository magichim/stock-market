import { useCallback, useEffect, useState } from 'react'
import { fetchMe, hasSession, loginUrl, logout, type User } from './api'

// 메인 페이지 — 로그인 공유 테스트용: 현재 사용자, has_session 쿠키 여부, 로그인·로그아웃
export function App() {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setUser(await fetchMe())
    } catch (err) {
      setError(err instanceof Error ? err.message : '요청에 실패했습니다.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const handleLogout = async () => {
    await logout()
    await load()
  }

  return (
    <main className="page">
      <h1>AGISAJA Stock</h1>
      <section className="card">
        {loading ? (
          <p className="dim">로그인 상태 확인 중…</p>
        ) : user ? (
          <p>
            <strong>{user.username}</strong> 님으로 로그인됨 · id {user.id}
          </p>
        ) : (
          <p>로그인하지 않았습니다.</p>
        )}
        {error && <p className="error">{error}</p>}
        <p className="dim">has_session 쿠키: {hasSession() ? '있음' : '없음'}</p>
        <div className="actions">
          {user ? (
            <button onClick={handleLogout}>로그아웃</button>
          ) : (
            <a className="button" href={loginUrl()}>
              agisaja.com에서 로그인
            </a>
          )}
          <button className="secondary" onClick={load}>
            다시 확인
          </button>
        </div>
      </section>
    </main>
  )
}
