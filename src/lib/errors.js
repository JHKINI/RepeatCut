// 서버가 돌려준 오류 메시지(detail)를 꺼낸다. 없으면 기본 문장을 쓴다.
// (FastAPI의 입력 형식 오류는 detail이 배열로 오기 때문에 문자열일 때만 그대로 보여준다)
export async function readError(response, fallback) {
  const body = await response.json().catch(() => ({}))
  return typeof body.detail === 'string' && body.detail ? body.detail : `${fallback} (HTTP ${response.status})`
}
