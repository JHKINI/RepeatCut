# RepeatCut 실행 방법

Windows(PowerShell) 기준입니다. 터미널을 **2개** 사용합니다. (백엔드 1개, 프론트 1개)

## 0. 준비물

- Python 3.10 이상
- Node.js 18 이상

## 1. 처음 한 번: 설치

프로젝트 루트(`RepeatCut` 폴더)에서 실행합니다.

```powershell
pip install -r requirements.txt
pip install pytest httpx
npm install
```

`node_modules`가 중간에 끊긴 채 남아 있으면 폴더를 지우고 `npm install`을 다시 실행합니다.

## 2. 테스트 (선택, 처음 한 번 권장)

```powershell
pytest backend/tests -v
```

- 34개 모두 통과해야 합니다.
- 임시 DB를 쓰므로 실제 `data/app.db`는 건드리지 않습니다.

## 3. 백엔드 실행 (터미널 1)

```powershell
cd backend
uvicorn main:app --reload --port 8000
```

- 정상 확인: 브라우저에서 http://127.0.0.1:8000/api/health 가 `{"ok": true, "schema_version": 5, "storage": "local"}` 형태로 나오면 됩니다.
- 이전 버전 DB(v2)가 있으면 처음 켤 때 v5로 올라가고, `data\app.db.backup-v2-...` 백업이 자동으로 생깁니다.

## 4. 프론트 실행 (터미널 2)

```powershell
cd 프로젝트루트
npm run dev
```

- 접속: http://localhost:5173
- 처음에는 회원가입부터 합니다. 처음 가입한 계정이 기존(주인 없는) 기록을 넘겨받습니다.

## 5. 화면 사용 순서

1. 회원가입 / 로그인
2. 오답 기록 첫 화면: 시험 선택 → 시험 유형 선택 → 연도별 회차 목록(검색 가능) → 문제지의 오답 목록
3. `＋ 오답 등록`: 문제 이미지 자르기, 문제지·키워드·오답 이유 선택
4. 통계 탭: 키워드별, 이유별, 문제지별 오답률, 다시 풀어도 틀린 문제
5. 통계 탭의 AI 학습 추천 (오답 3개 이상일 때)

## 6. Gemini 학습 추천 (선택)

백엔드를 켜기 전에, **같은 터미널**에서 키를 설정합니다.

```powershell
$env:REPEATCUT_GEMINI_API_KEY="발급받은키"
cd backend
uvicorn main:app --reload --port 8000
```

- 키가 없으면 규칙 기반 추천으로 동작합니다.
- 모델 기본값은 `gemini-3.8-flash`입니다. 키로 호출이 안 되면 모델 이름을 바꿉니다.

```powershell
$env:REPEATCUT_GEMINI_MODEL="사용할 모델 이름"
```

- 응답 대기 시간 변경: `$env:REPEATCUT_GEMINI_TIMEOUT="20"` (초)
- 같은 통계는 캐시를 재사용하고, 백엔드를 다시 켜면 캐시가 초기화됩니다.

## 7. 자주 막히는 경우

| 증상 | 확인할 것 |
|---|---|
| 로그인·목록에서 에러 | 백엔드(터미널 1)가 켜져 있는지, 포트가 8000인지 |
| 프론트 API 주소를 바꾸고 싶음 | `VITE_API_ORIGIN` (기본 `http://127.0.0.1:8000`, `.env.example` 참고) |
| 추천이 규칙 기반으로만 나옴 | 키 설정 여부, 오답 3개 이상 여부, 백엔드 터미널의 오류 메시지 |
| 자동완성이 안 뜸 | 시험명·키워드를 한 번도 등록하지 않은 경우, 목록이 비어 있음 |
| 앞서 만든 `node_modules` 오류 | 폴더 삭제 후 `npm install` |

## 8. 디자인 되돌리기 (Apple 스타일 테마)

화면 디자인은 `src/theme-apple.css` 한 파일로 덮어씌운 것입니다. 예전 디자인(소프트 글래스)으로 되돌리려면
`src/main.jsx`에서 아래 한 줄을 지우거나 맨 앞에 `//`를 붙입니다.

```js
import './theme-apple.css'
```

`index.css`와 `vibe-design` 폴더는 건드리지 않았으므로 이 한 줄만으로 원래대로 돌아갑니다.
색을 조금 바꾸고 싶으면 `theme-apple.css` 맨 위 `--color-primary` 같은 변수만 고칩니다.

## 9. 환경변수 요약

| 이름 | 기본값 | 설명 |
|---|---|---|
| `REPEATCUT_GEMINI_API_KEY` | (없음) | Gemini 키. `GEMINI_API_KEY`도 인식 |
| `REPEATCUT_GEMINI_MODEL` | `gemini-3.8-flash` | 학습 추천 모델 |
| `REPEATCUT_GEMINI_TIMEOUT` | `20` | 응답 대기(초) |
| `REPEATCUT_CORS_ORIGINS` | `localhost:5173/5174` | 프론트 주소 목록 |
| `VITE_API_ORIGIN` | `http://127.0.0.1:8000` | 프론트가 호출할 API 주소 |

배포 관련 설정(S3, 외부 DB 등)은 `README.md`를 참고합니다.
