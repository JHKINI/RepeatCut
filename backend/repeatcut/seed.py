"""처음 만들어진 DB에만 넣는 예시 데이터.
(이미지 파일도 이미지 저장소를 통해 저장하므로, 저장소가 S3여도 똑같이 동작한다)"""
from datetime import datetime, timedelta

from .rules import DEFAULT_EXAM
from . import repository as repo


def make_seed_svg(label):
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="720" height="460" viewBox="0 0 720 460">
          <rect width="720" height="460" rx="28" fill="#f6faf8"/>
          <rect x="38" y="34" width="644" height="392" rx="20" fill="#ffffff" stroke="#4b6258" stroke-width="5"/>
          <rect x="68" y="66" width="118" height="48" rx="24" fill="#dceddf"/>
          <text x="92" y="98" font-family="sans-serif" font-size="25" font-weight="700" fill="#355342">키워드 A</text>
          <text x="68" y="172" font-family="sans-serif" font-size="32" font-weight="700" fill="#283c33">{label}</text>
          <line x1="68" y1="206" x2="618" y2="206" stroke="#c9d9cf" stroke-width="4"/>
          <text x="68" y="268" font-family="sans-serif" font-size="26" fill="#355342">핵심 개념을 적용해 식을 완성하세요.</text>
          <text x="68" y="326" font-family="sans-serif" font-size="32" fill="#283c33">(  x + 2  )  ×  3  =  ?</text>
          <circle cx="616" cy="346" r="34" fill="#d9eee4"/>
          <text x="603" y="357" font-family="sans-serif" font-size="26" font-weight="700" fill="#355342">?</text>
        </svg>'''


def insert_seed_data(conn, storage):
    papers = {
        "지역농협 6급 대비 문제집": ("문제집", "기타"),
        "지역농협 NCS 실전모의고사": ("모의고사", "기타"),
    }
    paper_ids = {}
    for title, (exam_type, round_) in papers.items():
        # 주인(user_id)은 None: 예시 데이터는 처음 가입하는 회원이 넘겨받는다
        paper_ids[title], _ = repo.get_or_create_paper(conn, None, DEFAULT_EXAM, 2025, exam_type, round_, title)

    examples = [
        ("지역농협 6급 대비 문제집", "12", 18, "A", "문제 잘못 읽음", "문장의 핵심 조건을 끝까지 확인하지 않고 계산을 시작했어요.", 6),
        ("지역농협 6급 대비 문제집", "18", 24, "B", "계산실수", "자료의 단위를 바꾸는 과정에서 기준 값을 놓쳤어요.", 5),
        ("지역농협 NCS 실전모의고사", "7", 11, "C", "개념이해부족", "표의 증감률과 실제 수치를 같은 값으로 판단했어요.", 4),
        ("지역농협 6급 대비 문제집", "22", 31, "A", "문제 잘못 읽음", "보기의 예외 조건을 제외하지 못했어요.", 3),
        ("지역농협 NCS 실전모의고사", "15", 19, "B", "계산실수", "계산 순서를 바꾸면서 괄호 안의 조건을 놓쳤어요.", 2),
        ("지역농협 6급 대비 문제집", "29", 42, "C", "문제 잘못 읽음", "지문 속 비교 기준을 반대로 적용했어요.", 1),
        ("지역농협 NCS 실전모의고사", "34", 53, "A", "개념이해부족", "선택지의 범위를 넓게 해석해 답을 고르지 못했어요.", 0),
    ]
    for index, (paper_title, problem_no, page, keyword, reason_type, memo, days_ago) in enumerate(examples, start=1):
        image_no = f"IMG-NH-SEED-{index:04d}"
        filename = f"seed-nh_{index}.svg"
        if not storage.exists(filename):
            storage.save(filename, make_seed_svg(f"지역농협 예시 문제 {problem_no}번").encode("utf-8"), "image/svg+xml")
        created_at = (datetime.now() - timedelta(days=days_ago)).replace(hour=10 + index, minute=20, second=0, microsecond=0).isoformat(timespec="seconds")
        keyword_id = repo.get_or_create_keyword(conn, keyword)
        repo.insert_mistake(
            conn, paper_id=paper_ids[paper_title], problem_no=problem_no, page=page, keyword_id=keyword_id,
            reason_type=reason_type, memo=memo, my_answer="", correct_answer="",
            image_no=image_no, image_path=filename, created_at=created_at,
        )
