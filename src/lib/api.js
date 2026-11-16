import { clearToken, getToken, notifySessionExpired } from './auth';

// 백엔드 서버 주소. 배포할 때는 빌드 전에 환경변수 VITE_API_ORIGIN으로 바꾼다. (예: https://api.example.com)
//  - 설정 안 함  → 개발용 기본값 http://127.0.0.1:8000
//  - 빈 값("")   → 같은 주소에서 /api 로 요청 (프론트와 API를 같은 도메인 뒤에 둘 때)
const configuredOrigin = (import.meta.env && import.meta.env.VITE_API_ORIGIN) ?? 'http://127.0.0.1:8000';
const API_ORIGIN = String(configuredOrigin).replace(/\/+$/, '');

export const apiUrl = (path) => {
  if (/^https?:\/\//i.test(path)) return path;
  if (path.startsWith('/uploads/')) return `${API_ORIGIN}${path}`;
  return `${API_ORIGIN}/api/${path.replace(/^\/+/, '')}`;
};

// 모든 API 요청은 이 함수를 거친다.
//  - 로그인 토큰이 있으면 `Authorization: Bearer <토큰>` 헤더를 붙인다.
//  - 토큰을 보냈는데 서버가 401을 주면 로그인이 만료된 것이므로, 토큰을 지우고 로그인 화면으로 보낸다.
export async function api(path, init = {}) {
  const token = getToken();
  const headers = { ...(init.headers || {}) };
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(apiUrl(path), { ...init, headers });
  if (response.status === 401 && token) {
    clearToken();
    notifySessionExpired();
  }
  return response;
}

// GET 요청을 보내고 JSON을 돌려준다. 실패(HTTP 4xx/5xx)하면 에러를 던진다.
export async function getJson(path) {
  const response = await api(path);
  if (!response.ok) throw new Error(`요청 실패 (HTTP ${response.status}): ${path}`);
  return response.json();
}
