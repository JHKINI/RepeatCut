import { useState } from 'react'
import { api } from '../lib/api'
import { saveToken } from '../lib/auth'
import { readError } from '../lib/errors'

const MIN_PASSWORD_LENGTH = 8 // 서버(backend/repeatcut/rules.py)와 같은 값

// 로그인 / 회원가입 화면. 성공하면 토큰을 저장하고 onLogin(회원 정보)을 부른다.
export function AuthScreen({ onLogin }) {
  const [mode, setMode] = useState('login') // 'login' | 'register'
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [nickname, setNickname] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const isRegister = mode === 'register'

  const switchMode = (next) => {
    setMode(next)
    setMessage('')
  }

  const submit = async (event) => {
    event.preventDefault()
    setMessage('')
    if (isRegister && password.length < MIN_PASSWORD_LENGTH) {
      setMessage(`비밀번호는 ${MIN_PASSWORD_LENGTH}자 이상으로 입력해 주세요.`)
      return
    }
    setBusy(true)
    try {
      const body = isRegister ? { email, password, nickname } : { email, password }
      const response = await api(isRegister ? 'auth/register' : 'auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!response.ok) throw new Error(await readError(response, isRegister ? '가입하지 못했습니다.' : '로그인하지 못했습니다.'))
      const data = await response.json()
      saveToken(data.token)
      onLogin(data.user)
    } catch (err) {
      // fetch 자체가 실패하면(서버 꺼짐) TypeError가 온다
      setMessage(err instanceof TypeError ? '서버에 연결하지 못했습니다. 백엔드가 켜져 있는지 확인해 주세요.' : err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="auth-page">
      <form className="auth-card form-panel glass" onSubmit={submit}>
        <p className="eyebrow">{isRegister ? '회원가입' : '로그인'}</p>
        <h2>{isRegister ? '내 오답 노트를 만들어요' : '다시 오셨네요'}</h2>
        <label>이메일
          <input type="email" required autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@example.com" />
        </label>
        <label>비밀번호
          <input type="password" required autoComplete={isRegister ? 'new-password' : 'current-password'} value={password} onChange={(event) => setPassword(event.target.value)} />
        </label>
        {isRegister && <p className="field-hint">{MIN_PASSWORD_LENGTH}자 이상으로 정해 주세요.</p>}
        {isRegister && (
          <label>이름 (선택)
            <input value={nickname} maxLength={20} autoComplete="nickname" onChange={(event) => setNickname(event.target.value)} placeholder="화면에 보여줄 이름" />
          </label>
        )}
        {message && <p className="inline-error" role="alert">{message}</p>}
        <button className="button primary press" type="submit" disabled={busy}>
          {busy ? '확인하는 중…' : isRegister ? '가입하고 시작하기' : '로그인'}
        </button>
        <p className="auth-switch">
          {isRegister ? '이미 계정이 있나요?' : '처음이신가요?'}{' '}
          <button type="button" className="text-button" onClick={() => switchMode(isRegister ? 'login' : 'register')}>
            {isRegister ? '로그인' : '회원가입'}
          </button>
        </p>
      </form>
    </section>
  )
}
