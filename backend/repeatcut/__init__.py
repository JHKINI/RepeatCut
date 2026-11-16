"""RepeatCut 백엔드 구성 요소.

  rules.py          선택 목록·입력 한도·이름 규칙
  settings.py       환경변수 설정 (DB 경로, 이미지 저장소, CORS ...)
  database.py       SQLite 연결, 번호가 붙은 구조 변경(migration), 자동 백업
  repository.py     SQL 모음 (회원별 조건 user_id도 전부 여기서 건다)
  auth.py           비밀번호 해시, 로그인 토큰
  advice.py         통계 기반 학습 추천 (Gemini API, 실패하면 규칙 기반)
  image_storage.py  이미지 저장소 (로컬 폴더 / S3 호환)
  seed.py           처음 만든 DB에 넣는 예시 데이터
  bootstrap.py      서버 시작 시 DB 준비
"""
