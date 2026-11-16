"""입력 규칙: 선택 목록, 입력 한도, 값 정리 함수.

프론트는 GET /api/options로 선택 목록을 받아서 그대로 보여준다.
선택 목록을 바꾸고 싶으면 이 파일 한 곳만 고치면 된다.
(주의: 이미 저장된 데이터는 라벨 문자열 그대로 들어 있으므로, 라벨 이름을 바꾸면 DB의 기존 값도 UPDATE로 같이 바꿔야 한다)
"""
from datetime import datetime

# ── 선택 목록 ──
DEFAULT_EXAM = "지역농협"
EXAM_TYPES = ["기출", "모의고사", "문제집"]
ROUNDS = ["상반기", "하반기", "1회차", "2회차", "3회차", "4회차", "기타"]
REASON_TYPES = ["개념이해부족", "계산실수", "문제 잘못 읽음", "시간 부족", "찍어서 틀림", "기억 안 남", "기타"]
ANSWER_CHOICES = ["1", "2", "3", "4", "5"]  # 내가 고른 답 / 정답 칩 (5지선다)

# ── 입력 한도 ──
FIRST_YEAR = 2015  # 연도 선택 목록의 가장 오래된 연도
MAX_ANSWER_LENGTH = 20  # 답은 칩(1~5) 말고 나중에 주관식 값도 담을 수 있게 20자까지 허용
MAX_QUESTIONS = 500  # 문제지 문항 수 상한
MAX_KEYWORD_LENGTH = 50
MAX_EXAM_LENGTH = 30
MAX_TITLE_LENGTH = 60

# ── 로그인 ──
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 100
MAX_EMAIL_LENGTH = 100
MAX_NICKNAME_LENGTH = 20
SESSION_DAYS = 7  # 로그인 유지 기간(일). 지나면 다시 로그인해야 한다


def clean(text):
    """앞뒤 공백을 지우고, 중간의 연속 공백은 하나로 줄인다. ('농도  계산 ' -> '농도 계산')"""
    return " ".join((text or "").split())


def year_choices():
    """올해부터 FIRST_YEAR까지 (최신 연도가 맨 위)."""
    this_year = datetime.now().year
    return list(range(this_year, FIRST_YEAR - 1, -1))


def paper_display_title(exam, year, exam_type, round_, title):
    """문제지 이름. 직접 입력한 이름이 있으면 그걸 쓰고, 비어 있으면 자동으로 만든다.
    예) 2025 지역농협 상반기 / 2025 지역농협 1회차 모의고사
    (프론트의 src/lib/paperTitle.js와 같은 규칙)"""
    if title:
        return title
    parts = []
    if year:
        parts.append(str(year))
    parts.append(exam)
    if round_ and round_ != "기타":
        parts.append(round_)
    if exam_type and exam_type != "기출":
        parts.append(exam_type)
    return " ".join(parts)


def guess_exam_type(title):
    """예전 데이터를 옮길 때, 문제집 이름에 '모의'/'기출'이 들어 있으면 시험 구분을 추정한다."""
    if "모의" in title:
        return "모의고사"
    if "기출" in title:
        return "기출"
    return "문제집"
