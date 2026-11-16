// 로그인 토큰 보관.
//  - 로그인하면 서버가 준 토큰을 브라우저(localStorage)에 저장해 두고, api.js가 요청마다 헤더에 넣어 보낸다.
//  - 새로고침해도 로그인이 유지된다. 로그아웃하거나 서버가 "만료됐다(401)"고 하면 지운다.
const TOKEN_KEY = 'repeatcut.token'

// 시크릿 모드처럼 localStorage를 못 쓰는 브라우저에서는 이 변수에만 담아 둔다. (새로고침하면 로그아웃됨)
let memoryToken = ''

export function getToken() {
  try {
    return window.localStorage.getItem(TOKEN_KEY) || memoryToken
  } catch {
    return memoryToken
  }
}

export function saveToken(token) {
  memoryToken = token
  try {
    window.localStorage.setItem(TOKEN_KEY, token)
  } catch {
    // 저장이 막혀 있으면 memoryToken만 쓴다
  }
}

export function clearToken() {
  memoryToken = ''
  try {
    window.localStorage.removeItem(TOKEN_KEY)
  } catch {
    // 지울 것이 없다
  }
}

// 서버가 401(로그인 만료)을 돌려주면 App에 알려서 로그인 화면으로 보낸다.
let sessionExpiredHandler = null

export function setSessionExpiredHandler(handler) {
  sessionExpiredHandler = handler
}

export function notifySessionExpired() {
  if (sessionExpiredHandler) sessionExpiredHandler()
}
