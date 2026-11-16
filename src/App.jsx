import { useEffect, useState } from 'react'
import { AuthScreen } from './components/AuthScreen'
import { ExamBrowser } from './components/ExamBrowser'
import { RegisterMistake } from './components/RegisterMistake'
import { Stats } from './components/Stats'
import { api } from './lib/api'
import { clearToken, getToken, setSessionExpiredHandler } from './lib/auth'


export default function App() {
  const [screen, setScreen] = useState('library')
  // 로고를 누를 때마다 숫자를 바꿔서 오답 기록 화면을 처음 상태(상세 닫힘, 검색 초기화)로 다시 그린다
  const [homeKey, setHomeKey] = useState(0)
  const finish = () => setScreen('library')

  // ── 로그인 상태 ──
  // user: 로그인한 회원 {id, email, nickname}. 로그인 전에는 null.
  // checking: 저장된 토큰이 아직 쓸 수 있는지 서버에 물어보는 중 (그동안 로그인 화면이 깜빡이지 않게)
  const [user, setUser] = useState(null)
  const [checking, setChecking] = useState(Boolean(getToken()))

  useEffect(() => {
    // 어떤 요청이든 서버가 401(로그인 만료)을 주면 로그인 화면으로 돌아간다
    setSessionExpiredHandler(() => setUser(null))

    // 새로고침했을 때: 저장된 토큰이 있으면 누구 것인지 확인한다
    if (getToken()) {
      api('auth/me')
        .then((response) => (response.ok ? response.json() : null))
        .then((me) => setUser(me))
        .catch(() => setUser(null)) // 서버가 꺼져 있으면 로그인 화면을 보여준다 (토큰은 지우지 않는다)
        .finally(() => setChecking(false))
    }
    return () => setSessionExpiredHandler(null)
  }, [])

  const login = (nextUser) => {
    setUser(nextUser)
    setScreen('library')
    setHomeKey((key) => key + 1)
  }

  const logout = async () => {
    try {
      await api('auth/logout', { method: 'POST' }) // 서버의 로그인 상태도 지운다
    } catch {
      // 서버에 닿지 못해도 이 브라우저에서는 로그아웃한다
    }
    clearToken()
    setUser(null)
  }

  // 왼쪽 위 로고 클릭 → 홈(오답 기록 화면)
  const goHome = (event) => {
    event.preventDefault() // 페이지 새로고침 대신 화면만 바꾼다
    setScreen('library')
    setHomeKey((key) => key + 1)
  }

  return <div className="app-shell">
    <header className="site-header">
      <a className="brand-home" href="/" onClick={goHome} aria-label="Repeatcut 홈으로">
        <div className="brand-mark">R</div>
        <div><h1>Repeatcut</h1><p>틀린 문제를 잘라, 다시 맞히는 기록</p></div>
      </a>
      {user && (
        <>
          <nav className="header-nav" aria-label="주요 화면">
            <button className={screen === 'library' || screen === 'register' ? 'nav-button active' : 'nav-button'} onClick={() => setScreen('library')}>오답 기록</button>
            <button className={screen === 'stats' ? 'nav-button active' : 'nav-button'} onClick={() => setScreen('stats')}>통계</button>
          </nav>
          <div className="user-box">
            <span className="user-name" title={user.email}>{user.nickname || user.email}</span>
            <button className="text-button" onClick={logout}>로그아웃</button>
          </div>
        </>
      )}
    </header>
    <main>
      {checking ? (
        <div className="state-card">로그인 상태를 확인하는 중입니다.</div>
      ) : !user ? (
        <AuthScreen onLogin={login} />
      ) : screen === 'library' ? (
        <ExamBrowser key={homeKey} onRegister={() => setScreen('register')} />
      ) : screen === 'stats' ? (
        <Stats />
      ) : (
        <RegisterMistake onSaved={finish} onCancel={finish} />
      )}
    </main>
  </div>
}
