"""DB에 묻고 쓰는 SQL을 전부 이 파일에 모아 둔다. (main.py의 API 함수는 검사만 하고 여기 함수를 부른다)

■ 회원별 데이터 분리
  문제지(papers)에 주인(user_id)이 있고, 오답(mistakes)은 문제지를 통해 주인이 정해진다.
  그래서 문제지·오답·통계를 읽고 쓰는 함수는 모두 user_id를 받아서 `p.user_id = ?` 조건을 건다.
  → 남의 id를 주소에 직접 넣어도 "없는 것"으로 취급된다(404).
  새 SQL을 추가할 때도 이 조건을 빠뜨리지 않는다.

함수는 모두 첫 인자로 conn(DB 연결)을 받는다.
"""
from datetime import datetime
from typing import Optional

from .rules import ANSWER_CHOICES, REASON_TYPES, clean, paper_display_title

STATS_TOP_KEYWORDS = 10  # 키워드 순위에 보여줄 개수
STATS_MATRIX_KEYWORDS = 5  # '키워드 x 오답 이유' 표에 쓸 상위 키워드 개수
STATS_REPEAT_WRONG = 5  # '다시 풀어도 틀린 문제'에 보여줄 개수


def now_text():
    return datetime.now().isoformat(timespec="seconds")


# ──────────────────────────────────────────────
# 회원 / 로그인 상태
# ──────────────────────────────────────────────
def public_user(row):
    """응답에 넣어도 되는 회원 정보만 고른다. (password_hash는 절대 내보내지 않는다)"""
    return {"id": row["id"], "email": row["email"], "nickname": row["nickname"]}


def find_user_by_email(conn, email):
    """로그인용. password_hash가 들어 있으므로 이 결과를 그대로 응답하면 안 된다."""
    return conn.execute("SELECT id, email, nickname, password_hash FROM users WHERE email = ?", (email,)).fetchone()


def create_user(conn, email, password_hash, nickname):
    return conn.execute(
        "INSERT INTO users (email, password_hash, nickname, created_at) VALUES (?, ?, ?, ?)",
        (email, password_hash, nickname, now_text()),
    ).lastrowid


def get_user(conn, user_id):
    row = conn.execute("SELECT id, email, nickname FROM users WHERE id = ?", (user_id,)).fetchone()
    return public_user(row) if row else None


def count_users(conn):
    return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def claim_unowned_papers(conn, user_id):
    """주인이 없는 문제지(로그인 기능이 생기기 전에 만든 데이터, 예시 데이터)를 이 회원 것으로 만든다.
    오답은 문제지를 따라가므로 문제지만 바꾸면 된다. 옮긴 문제지 수를 돌려준다."""
    return conn.execute("UPDATE papers SET user_id = ? WHERE user_id IS NULL", (user_id,)).rowcount


def create_session(conn, user_id, token_hash, expires_at):
    conn.execute(
        "INSERT INTO sessions (user_id, token_hash, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (user_id, token_hash, now_text(), expires_at),
    )


def find_session_user(conn, token_hash):
    """토큰(의 해시)에 해당하는, 아직 만료되지 않은 로그인 상태의 회원. 없으면 None."""
    row = conn.execute(
        """SELECT u.id, u.email, u.nickname
           FROM sessions s JOIN users u ON u.id = s.user_id
           WHERE s.token_hash = ? AND s.expires_at > ?""",
        (token_hash, now_text()),
    ).fetchone()
    return public_user(row) if row else None


def delete_session(conn, token_hash):
    conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))


def delete_expired_sessions(conn):
    conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now_text(),))


# ──────────────────────────────────────────────
# 시험(자격증) 종류
# ──────────────────────────────────────────────
def get_or_create_exam(conn, name):
    name = clean(name)
    row = conn.execute("SELECT id FROM exams WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    return conn.execute("INSERT INTO exams (name, created_at) VALUES (?, ?)", (name, now_text())).lastrowid


def list_exams(conn, user_id):
    """이 회원이 문제지에 써 본 시험명 목록 (많이 쓴 순). 입력창 자동완성용."""
    rows = conn.execute(
        """SELECT e.id, e.name, COUNT(p.id) AS paper_count
           FROM exams e JOIN papers p ON p.exam_id = e.id
           WHERE p.user_id = ?
           GROUP BY e.id ORDER BY paper_count DESC, e.name ASC""",
        (user_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def user_has_exam(conn, user_id, exam_id):
    row = conn.execute("SELECT 1 FROM papers WHERE user_id = ? AND exam_id = ? LIMIT 1", (user_id, exam_id)).fetchone()
    return row is not None


def rename_exam(conn, user_id, exam_id, new_name):
    """내 문제지의 시험명을 new_name 으로 바꾸고, 바뀐 시험의 id를 돌려준다.
    exams 는 회원이 함께 쓰는 표(이름이 대소문자 구분 없이 하나뿐)라서 경우를 나눈다.
      - 다른 회원이 안 쓰는 시험이면 이름 자체를 고친다 (sqld → SQLD)
      - 다른 회원도 쓰고 있으면 내 문제지만 새 이름의 시험으로 옮긴다
      - 이미 있는 다른 시험 이름이면 내 문제지를 거기로 합친다 (같은 문제지가 겹치면 거절)"""
    shared = conn.execute(
        "SELECT 1 FROM papers WHERE exam_id = ? AND (user_id IS NULL OR user_id != ?) LIMIT 1", (exam_id, user_id)
    ).fetchone() is not None
    same = conn.execute("SELECT id FROM exams WHERE name = ?", (new_name,)).fetchone()  # 대소문자 구분 없이 찾는다

    if same is None:
        if not shared:
            conn.execute("UPDATE exams SET name = ? WHERE id = ?", (new_name, exam_id))
            return exam_id
        target = conn.execute("INSERT INTO exams (name, created_at) VALUES (?, ?)", (new_name, now_text())).lastrowid
    elif same["id"] == exam_id:
        if shared:
            raise ValueError("다른 사용자도 같은 이름의 시험을 쓰고 있어서 대소문자만 바꿀 수는 없어요.")
        conn.execute("UPDATE exams SET name = ? WHERE id = ?", (new_name, exam_id))
        return exam_id
    else:
        target = same["id"]
        for paper in conn.execute(
            "SELECT year, exam_type, round, title FROM papers WHERE user_id = ? AND exam_id = ?", (user_id, exam_id)
        ).fetchall():
            if find_paper_id(conn, user_id, target, paper["year"], paper["exam_type"], paper["round"], paper["title"]):
                raise ValueError("이미 있는 시험 이름이고, 같은 문제지가 겹쳐서 합칠 수 없어요.")

    conn.execute("UPDATE papers SET exam_id = ? WHERE user_id = ? AND exam_id = ?", (target, user_id, exam_id))
    delete_unused_exams(conn)
    return target


def count_exam_contents(conn, user_id, exam_id):
    row = conn.execute(
        """SELECT COUNT(DISTINCT p.id) AS papers, COUNT(m.id) AS mistakes
           FROM papers p LEFT JOIN mistakes m ON m.paper_id = p.id
           WHERE p.user_id = ? AND p.exam_id = ?""",
        (user_id, exam_id),
    ).fetchone()
    return {"papers": row["papers"], "mistakes": row["mistakes"]}


def delete_exam_for_user(conn, user_id, exam_id):
    """내 문제지 중 이 시험의 것을 오답(과 다시 푼 기록)까지 지운다. 지운 오답의 이미지 파일 이름 목록을 돌려준다."""
    rows = conn.execute(
        """SELECT m.id, m.image_path FROM mistakes m JOIN papers p ON p.id = m.paper_id
           WHERE p.user_id = ? AND p.exam_id = ?""",
        (user_id, exam_id),
    ).fetchall()
    for row in rows:
        delete_mistake(conn, row["id"])
    conn.execute("DELETE FROM papers WHERE user_id = ? AND exam_id = ?", (user_id, exam_id))
    delete_unused_keywords(conn)
    delete_unused_exams(conn)
    return sorted({row["image_path"] for row in rows})


def delete_unused_exams(conn):
    """문제지가 하나도 안 걸려 있는 시험명은 정리한다. (오타로 만든 시험명이 남지 않게)"""
    conn.execute("DELETE FROM exams WHERE id NOT IN (SELECT DISTINCT exam_id FROM papers)")


# ──────────────────────────────────────────────
# 문제지
# ──────────────────────────────────────────────
PAPER_SELECT = """
    SELECT p.id, p.exam_id, e.name AS exam, p.year, p.exam_type, p.round, p.title, p.total_questions, p.created_at,
           COUNT(m.id) AS mistake_count,
           COALESCE(MAX(m.created_at), p.created_at) AS last_used
    FROM papers p
    JOIN exams e ON e.id = p.exam_id
    LEFT JOIN mistakes m ON m.paper_id = p.id
"""


def paper_to_dict(row):
    data = dict(row)
    data["display_title"] = paper_display_title(data["exam"], data["year"], data["exam_type"], data["round"], data["title"])
    return data


def paper_exists(conn, user_id, paper_id):
    row = conn.execute("SELECT 1 FROM papers WHERE id = ? AND user_id = ?", (paper_id, user_id)).fetchone()
    return row is not None


def get_paper(conn, user_id, paper_id):
    row = conn.execute(PAPER_SELECT + " WHERE p.id = ? AND p.user_id = ? GROUP BY p.id", (paper_id, user_id)).fetchone()
    return paper_to_dict(row) if row else None


def list_papers(conn, user_id):
    """가장 최근에 쓴 문제지가 맨 위."""
    rows = conn.execute(
        PAPER_SELECT + " WHERE p.user_id = ? GROUP BY p.id ORDER BY last_used DESC, p.id DESC", (user_id,)
    ).fetchall()
    return [paper_to_dict(row) for row in rows]


def find_paper_id(conn, user_id, exam_id, year, exam_type, round_, title):
    # user_id와 year는 NULL일 수 있어서 '=' 대신 'IS'를 쓴다 (NULL끼리도 같다고 비교됨)
    # (user_id가 NULL인 경우 = 주인이 아직 없는 예시 데이터)
    row = conn.execute(
        """SELECT id FROM papers
           WHERE user_id IS ? AND exam_id = ? AND year IS ? AND exam_type = ? AND round = ? AND title = ?""",
        (user_id, exam_id, year, exam_type, round_, title),
    ).fetchone()
    return row["id"] if row else None


def get_or_create_paper(conn, user_id, exam, year, exam_type, round_, title, created_at=None, total_questions=None):
    """(paper_id, 새로 만들었는지) 를 돌려준다. exam은 시험명(문자열)이고, exams 테이블에 없으면 만든다."""
    exam_id = get_or_create_exam(conn, exam)
    existing = find_paper_id(conn, user_id, exam_id, year, exam_type, round_, title)
    if existing:
        return existing, False
    cursor = conn.execute(
        """INSERT INTO papers (user_id, exam_id, year, exam_type, round, title, total_questions, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, exam_id, year, exam_type, round_, title, total_questions, created_at or now_text()),
    )
    return cursor.lastrowid, True


def fill_total_questions_if_empty(conn, paper_id, total_questions):
    """문항 수가 비어 있는 문제지에만 값을 채운다. (이미 있는 값은 덮어쓰지 않는다)"""
    conn.execute("UPDATE papers SET total_questions = ? WHERE id = ? AND total_questions IS NULL", (total_questions, paper_id))


def update_paper(conn, user_id, paper_id, exam_id, year, exam_type, round_, title, total_questions):
    conn.execute(
        """UPDATE papers SET exam_id = ?, year = ?, exam_type = ?, round = ?, title = ?, total_questions = ?
           WHERE id = ? AND user_id = ?""",
        (exam_id, year, exam_type, round_, title, total_questions, paper_id, user_id),
    )


def count_mistakes_in_paper(conn, paper_id):
    return conn.execute("SELECT COUNT(*) FROM mistakes WHERE paper_id = ?", (paper_id,)).fetchone()[0]


def delete_paper(conn, user_id, paper_id):
    conn.execute("DELETE FROM papers WHERE id = ? AND user_id = ?", (paper_id, user_id))


# ──────────────────────────────────────────────
# 키워드
# ──────────────────────────────────────────────
def list_keywords(conn, user_id):
    """자동완성용. 이 회원의 오답이 걸려 있는 키워드만, 많이 쓴 순서로."""
    rows = conn.execute(
        """SELECT k.id, k.name, COUNT(m.id) AS count
           FROM keywords k
           JOIN mistakes m ON m.keyword_id = k.id
           JOIN papers p ON p.id = m.paper_id
           WHERE p.user_id = ?
           GROUP BY k.id ORDER BY count DESC, k.name ASC""",
        (user_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_or_create_keyword(conn, name):
    name = clean(name)
    row = conn.execute("SELECT id FROM keywords WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    return conn.execute("INSERT INTO keywords (name) VALUES (?)", (name,)).lastrowid


def delete_unused_keywords(conn):
    """오답이 하나도 안 걸려 있는 키워드는 정리한다. (오타로 만든 키워드가 목록에 남지 않게)"""
    conn.execute("DELETE FROM keywords WHERE id NOT IN (SELECT DISTINCT keyword_id FROM mistakes)")


# ──────────────────────────────────────────────
# 오답
#   다시 푼 기록(attempts)의 요약도 같이 읽는다:
#     wrong_total        이 문제를 틀린 총 횟수 = 처음 등록 1번 + 다시 풀어서 또 틀린 횟수
#     attempt_count      다시 푼 횟수
#     correct_count      그중 맞힌 횟수
#     last_is_correct    가장 최근에 다시 풀었을 때 맞혔는지 (1/0, 푼 적 없으면 NULL)
#     last_attempted_at  가장 최근에 다시 푼 시각
# ──────────────────────────────────────────────
MISTAKE_SELECT = """
    SELECT m.id, m.paper_id, m.problem_no, m.page, m.keyword_id, m.reason_type, m.memo,
           m.my_answer, m.correct_answer,
           m.image_no, m.image_path, m.created_at,
           k.name AS keyword,
           e.name AS exam, p.year, p.exam_type, p.round, p.title AS paper_custom_title,
           (SELECT COUNT(*) FROM attempts a WHERE a.mistake_id = m.id AND a.is_correct = 0) + 1 AS wrong_total,
           (SELECT COUNT(*) FROM attempts a WHERE a.mistake_id = m.id) AS attempt_count,
           (SELECT COALESCE(SUM(a.is_correct), 0) FROM attempts a WHERE a.mistake_id = m.id) AS correct_count,
           (SELECT a.is_correct FROM attempts a WHERE a.mistake_id = m.id
             ORDER BY a.attempted_at DESC, a.id DESC LIMIT 1) AS last_is_correct,
           (SELECT a.attempted_at FROM attempts a WHERE a.mistake_id = m.id
             ORDER BY a.attempted_at DESC, a.id DESC LIMIT 1) AS last_attempted_at
    FROM mistakes m
    JOIN papers p ON p.id = m.paper_id
    JOIN exams e ON e.id = p.exam_id
    JOIN keywords k ON k.id = m.keyword_id
"""


def mistake_to_dict(row):
    data = dict(row)
    custom_title = data.pop("paper_custom_title")
    data["paper_title"] = paper_display_title(data["exam"], data["year"], data["exam_type"], data["round"], custom_title)
    return data


def mistake_exists(conn, user_id, mistake_id):
    row = conn.execute(
        "SELECT 1 FROM mistakes m JOIN papers p ON p.id = m.paper_id WHERE m.id = ? AND p.user_id = ?",
        (mistake_id, user_id),
    ).fetchone()
    return row is not None


def get_mistake(conn, user_id, mistake_id):
    row = conn.execute(MISTAKE_SELECT + " WHERE m.id = ? AND p.user_id = ?", (mistake_id, user_id)).fetchone()
    return mistake_to_dict(row) if row else None


def find_same_problem(conn, user_id, paper_id, problem_no):
    """같은 문제지의 같은 문제 번호로 이미 등록한 오답의 id. 없으면 None.
    (같은 문제를 또 틀리면 오답을 새로 만들지 않고 '다시 푼 기록'에 쌓기 위해 쓴다. 번호는 대소문자 무시)"""
    row = conn.execute(
        """SELECT m.id FROM mistakes m JOIN papers p ON p.id = m.paper_id
           WHERE p.user_id = ? AND m.paper_id = ? AND m.problem_no = ? COLLATE NOCASE
           ORDER BY m.id LIMIT 1""",
        (user_id, paper_id, clean(problem_no)),
    ).fetchone()
    return row["id"] if row else None


def get_mistake_image_path(conn, user_id, mistake_id):
    row = conn.execute(
        "SELECT m.image_path FROM mistakes m JOIN papers p ON p.id = m.paper_id WHERE m.id = ? AND p.user_id = ?",
        (mistake_id, user_id),
    ).fetchone()
    return row["image_path"] if row else None


def list_mistakes(conn, user_id, keyword: Optional[str] = None, order="newest", paper_id: Optional[int] = None):
    order_by = "m.created_at ASC, m.id ASC" if order == "oldest" else "m.created_at DESC, m.id DESC"
    # 조건을 하나씩 붙인다. 회원 조건(p.user_id)은 항상 들어간다.
    where = ["p.user_id = ?"]
    params = [user_id]
    if keyword and keyword.strip():
        where.append("k.name LIKE ?")
        params.append(f"%{keyword.strip()}%")
    if paper_id is not None:
        where.append("p.id = ?")
        params.append(paper_id)
    rows = conn.execute(f"{MISTAKE_SELECT} WHERE {' AND '.join(where)} ORDER BY {order_by}", params).fetchall()
    return [mistake_to_dict(row) for row in rows]


def mistake_trend(conn, user_id):
    rows = conn.execute(
        """SELECT substr(m.created_at, 1, 10) AS date, COUNT(*) AS count
           FROM mistakes m JOIN papers p ON p.id = m.paper_id
           WHERE p.user_id = ?
           GROUP BY substr(m.created_at, 1, 10) ORDER BY date ASC""",
        (user_id,),
    ).fetchall()
    return [dict(row) for row in rows]


# 아래 쓰기 함수들은 mistake_id / paper_id가 이 회원 것인지 main.py에서 먼저 확인한 뒤에 부른다.
def insert_mistake(conn, *, paper_id, problem_no, page, keyword_id, reason_type, memo, my_answer, correct_answer,
                   image_no, image_path, created_at=None):
    return conn.execute(
        """INSERT INTO mistakes
           (paper_id, problem_no, page, keyword_id, reason_type, memo, my_answer, correct_answer,
            image_no, image_path, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (paper_id, problem_no, page, keyword_id, reason_type, memo, my_answer, correct_answer,
         image_no, image_path, created_at or now_text()),
    ).lastrowid


def update_mistake(conn, mistake_id, *, paper_id, problem_no, page, keyword_id, reason_type, memo, my_answer, correct_answer):
    conn.execute(
        """UPDATE mistakes
           SET paper_id = ?, problem_no = ?, page = ?, keyword_id = ?, reason_type = ?, memo = ?,
               my_answer = ?, correct_answer = ?
           WHERE id = ?""",
        (paper_id, problem_no, page, keyword_id, reason_type, memo, my_answer, correct_answer, mistake_id),
    )


def update_mistake_image(conn, mistake_id, image_path):
    """문제 이미지 파일을 새 파일로 바꾼다. (이미지 번호 image_no는 그대로)"""
    conn.execute("UPDATE mistakes SET image_path = ? WHERE id = ?", (image_path, mistake_id))


def count_image_references(conn, image_path):
    """이 이미지 파일을 쓰는 오답이 몇 개인지. (예전 데이터는 같은 파일을 여러 오답이 가리킬 수 있다)"""
    return conn.execute("SELECT COUNT(*) FROM mistakes WHERE image_path = ?", (image_path,)).fetchone()[0]


def delete_mistake(conn, mistake_id):
    """오답을 지운다. 다시 푼 기록(attempts)은 ON DELETE CASCADE로 같이 지워진다."""
    conn.execute("DELETE FROM mistakes WHERE id = ?", (mistake_id,))


# ──────────────────────────────────────────────
# 다시 푼 기록
# ──────────────────────────────────────────────
def list_attempts(conn, mistake_id):
    """최근에 푼 것이 맨 위."""
    rows = conn.execute(
        """SELECT id, mistake_id, is_correct, my_answer, reason_type, attempted_at FROM attempts
           WHERE mistake_id = ? ORDER BY attempted_at DESC, id DESC""",
        (mistake_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def insert_attempt(conn, mistake_id, is_correct, my_answer="", reason_type=""):
    """my_answer, reason_type: 또 틀렸을 때 그때 고른 답과 틀린 이유. 맞혔을 때는 둘 다 비워 둔다."""
    return conn.execute(
        "INSERT INTO attempts (mistake_id, is_correct, my_answer, reason_type, attempted_at) VALUES (?, ?, ?, ?, ?)",
        (mistake_id, 1 if is_correct else 0, my_answer, reason_type, now_text()),
    ).lastrowid


def delete_attempt(conn, mistake_id, attempt_id):
    """지운 줄 수를 돌려준다. (0이면 그 오답에 그런 기록이 없다는 뜻)"""
    return conn.execute("DELETE FROM attempts WHERE id = ? AND mistake_id = ?", (attempt_id, mistake_id)).rowcount


# ──────────────────────────────────────────────
# 통계
# ──────────────────────────────────────────────
def _answer_distribution(conn, column, scope, args):
    """내가 고른 답(my_answer) 또는 정답(correct_answer)의 번호별 분포.
    1~5는 0건이어도 항상 넣고, 그 밖의 값(주관식 등)은 있을 때만 뒤에 붙인다.
    my_answer는 처음 등록할 때 고른 답에, 다시 풀어서 또 틀렸을 때 고른 답(attempts.my_answer)도 더한다."""
    assert column in ("my_answer", "correct_answer")  # SQL 문자열에 직접 넣는 값이라 이 두 개만 허용
    rows = conn.execute(
        f"SELECT m.{column} AS answer, COUNT(*) AS count FROM mistakes m {scope} AND m.{column} != '' GROUP BY m.{column}",
        args,
    ).fetchall()
    counts = {row["answer"]: row["count"] for row in rows}
    if column == "my_answer":
        again_rows = conn.execute(
            f"""SELECT a.my_answer AS answer, COUNT(*) AS count
                FROM attempts a JOIN mistakes m ON m.id = a.mistake_id {scope}
                AND a.is_correct = 0 AND a.my_answer != '' GROUP BY a.my_answer""",
            args,
        ).fetchall()
        for row in again_rows:
            counts[row["answer"]] = counts.get(row["answer"], 0) + row["count"]
    answers = ANSWER_CHOICES + sorted(answer for answer in counts if answer not in ANSWER_CHOICES)
    return {
        "sample": sum(counts.values()),  # 입력된 답의 개수 (표본 수)
        "items": [{"answer": answer, "count": counts.get(answer, 0)} for answer in answers],
    }


def _retry_stats(conn, scope, condition, args, total):
    """다시 풀기 통계. '해결'과 '아직 틀림'은 가장 최근에 다시 푼 결과를 기준으로 나눈다.
    scope는 get_stats의 공통 조건 전체, condition은 그중 WHERE 뒤쪽만."""
    row = conn.execute(
        f"""SELECT COUNT(*) AS attempts, COALESCE(SUM(a.is_correct), 0) AS correct
            FROM attempts a JOIN mistakes m ON m.id = a.mistake_id {scope}""",
        args,
    ).fetchone()

    # 오답마다 가장 최근 결과를 하나씩 꺼낸다
    last_rows = conn.execute(
        f"""SELECT (SELECT a.is_correct FROM attempts a WHERE a.mistake_id = m.id
                     ORDER BY a.attempted_at DESC, a.id DESC LIMIT 1) AS last_is_correct
            FROM mistakes m {scope}""",
        args,
    ).fetchall()
    solved = sum(1 for item in last_rows if item["last_is_correct"] == 1)
    still_wrong = sum(1 for item in last_rows if item["last_is_correct"] == 0)

    # 다시 풀어서 또 틀린 횟수가 많은 문제
    repeat_rows = conn.execute(
        f"""SELECT m.id AS mistake_id, m.problem_no, m.my_answer, m.correct_answer, m.reason_type, k.name AS keyword,
                   e.name AS exam, p.year, p.exam_type, p.round, p.title,
                   COUNT(a.id) AS attempt_count,
                   SUM(CASE WHEN a.is_correct = 0 THEN 1 ELSE 0 END) AS wrong_count
            FROM attempts a
            JOIN mistakes m ON m.id = a.mistake_id
            JOIN keywords k ON k.id = m.keyword_id
            JOIN papers p ON p.id = m.paper_id
            JOIN exams e ON e.id = p.exam_id
            WHERE {condition}
            GROUP BY m.id HAVING wrong_count > 0
            ORDER BY wrong_count DESC, m.id DESC LIMIT ?""",
        (*args, STATS_REPEAT_WRONG),
    ).fetchall()
    repeat_wrong = []
    for item in repeat_rows:
        # 이 문제를 틀릴 때마다 고른 답과 이유: 처음 등록할 때 것 + 또 틀릴 때마다의 것 (입력한 것만, 오래된 순)
        again = conn.execute(
            """SELECT my_answer, reason_type FROM attempts
               WHERE mistake_id = ? AND is_correct = 0 ORDER BY attempted_at ASC, id ASC""",
            (item["mistake_id"],),
        ).fetchall()
        wrong_answers = [answer for answer in [item["my_answer"]] + [row["my_answer"] for row in again] if answer]
        wrong_reasons = [reason for reason in [item["reason_type"]] + [row["reason_type"] for row in again] if reason]
        repeat_wrong.append({
            "mistake_id": item["mistake_id"],
            "paper_title": paper_display_title(item["exam"], item["year"], item["exam_type"], item["round"], item["title"]),
            "problem_no": item["problem_no"],
            "keyword": item["keyword"],
            "attempt_count": item["attempt_count"],
            "wrong_count": item["wrong_count"],  # 다시 풀어서 또 틀린 횟수
            "wrong_total": item["wrong_count"] + 1,  # 처음 등록까지 합친 틀린 횟수
            "wrong_answers": wrong_answers,
            "wrong_reasons": wrong_reasons,
            "correct_answer": item["correct_answer"],
        })
    return {
        "attempts": row["attempts"],  # 다시 푼 총 횟수
        "correct": row["correct"],  # 그중 맞힌 횟수
        "correct_rate": round(row["correct"] / row["attempts"], 3) if row["attempts"] else None,
        "solved": solved,  # 최근에 다시 풀어서 맞힌 오답 수
        "still_wrong": still_wrong,  # 최근에 다시 풀어도 틀린 오답 수
        "not_retried": total - solved - still_wrong,  # 아직 한 번도 다시 안 푼 오답 수
        "repeat_wrong": repeat_wrong,
    }


def get_stats(conn, user_id, paper_id=None):
    """키워드별 / 오답 이유별 / 키워드x이유 / 문제지별 / 답 번호별 / 다시 풀기 통계.
    이 회원의 오답만 집계하고, paper_id를 주면 그중 그 문제지의 오답만 집계한다."""
    # scope: 모든 집계 SQL의 `FROM mistakes m ...` 뒤에 붙이는 공통 조건 (항상 WHERE로 끝나므로 뒤에 AND를 더 붙일 수 있다)
    condition = "p.user_id = ?"
    args = (user_id,)
    if paper_id:
        condition += " AND m.paper_id = ?"
        args = (user_id, paper_id)
    scope = f"JOIN papers p ON p.id = m.paper_id WHERE {condition}"

    total = conn.execute(f"SELECT COUNT(*) FROM mistakes m {scope}", args).fetchone()[0]

    # 1) 키워드별 오답 수 (많은 순)
    keyword_rows = conn.execute(
        f"""SELECT k.id AS keyword_id, k.name, COUNT(*) AS count
            FROM mistakes m JOIN keywords k ON k.id = m.keyword_id {scope}
            GROUP BY k.id ORDER BY count DESC, k.name ASC LIMIT ?""",
        (*args, STATS_TOP_KEYWORDS),
    ).fetchall()

    # 2), 3)에서 쓰는 "틀린 기록" = 처음 등록(mistakes) + 또 틀린 기록(attempts 중 틀림, 이유를 입력한 것).
    # 같은 문제를 여러 번 틀리면 틀릴 때마다의 이유가 각각 한 건으로 세어진다.
    pair_counts = {}  # (keyword_id, reason_type) -> 건수
    first_rows = conn.execute(
        f"SELECT m.keyword_id, m.reason_type, COUNT(*) AS count FROM mistakes m {scope} GROUP BY m.keyword_id, m.reason_type",
        args,
    ).fetchall()
    again_rows = conn.execute(
        f"""SELECT m.keyword_id, a.reason_type, COUNT(*) AS count
            FROM attempts a JOIN mistakes m ON m.id = a.mistake_id {scope}
            AND a.is_correct = 0 AND a.reason_type != ''
            GROUP BY m.keyword_id, a.reason_type""",
        args,
    ).fetchall()
    for row in list(first_rows) + list(again_rows):
        key = (row["keyword_id"], row["reason_type"])
        pair_counts[key] = pair_counts.get(key, 0) + row["count"]

    # 2) 오답 이유별 건수와 비율 (0건인 이유도 포함)
    reason_counts = {}
    for (keyword_id, reason), count in pair_counts.items():
        reason_counts[reason] = reason_counts.get(reason, 0) + count
    reason_total = sum(reason_counts.values())
    reasons = []
    for reason in REASON_TYPES:
        count = reason_counts.get(reason, 0)
        reasons.append({"reason_type": reason, "count": count, "ratio": round(count / reason_total, 3) if reason_total else 0})

    # 3) 상위 키워드 x 오답 이유
    matrix_rows = []
    for keyword in keyword_rows[:STATS_MATRIX_KEYWORDS]:
        counts = {reason: pair_counts.get((keyword["keyword_id"], reason), 0) for reason in REASON_TYPES}
        matrix_rows.append({"keyword_id": keyword["keyword_id"], "name": keyword["name"], "total": sum(counts.values()), "counts": counts})

    # 4) 문제지별 오답 수와 오답률 (문항 수를 입력한 문제지만 오답률 계산)
    paper_where, paper_args = "WHERE p.user_id = ?", (user_id,)
    if paper_id:
        paper_where, paper_args = "WHERE p.user_id = ? AND p.id = ?", (user_id, paper_id)
    paper_rows = conn.execute(
        f"""SELECT p.id, e.name AS exam, p.year, p.exam_type, p.round, p.title, p.total_questions,
                   COUNT(m.id) AS mistake_count
            FROM papers p
            JOIN exams e ON e.id = p.exam_id
            LEFT JOIN mistakes m ON m.paper_id = p.id
            {paper_where}
            GROUP BY p.id ORDER BY mistake_count DESC, p.id DESC""",
        paper_args,
    ).fetchall()
    papers = []
    for row in paper_rows:
        total_questions = row["total_questions"]
        papers.append({
            "paper_id": row["id"],
            "display_title": paper_display_title(row["exam"], row["year"], row["exam_type"], row["round"], row["title"]),
            "mistake_count": row["mistake_count"],
            "total_questions": total_questions,
            "wrong_rate": round(row["mistake_count"] / total_questions, 3) if total_questions else None,
        })

    # 5) 내가 고른 답 / 정답 번호 분포
    answers = {
        "my_answer": _answer_distribution(conn, "my_answer", scope, args),
        "correct_answer": _answer_distribution(conn, "correct_answer", scope, args),
    }

    return {
        "total": total,
        "keywords": [dict(row) for row in keyword_rows],
        "reasons": reasons,
        "reason_total": reason_total,  # 이유가 기록된 틀린 기록 수 (처음 등록 + 또 틀림)
        "keyword_reasons": {"reason_types": REASON_TYPES, "rows": matrix_rows},
        "papers": papers,
        "answers": answers,
        "retry": _retry_stats(conn, scope, condition, args, total),  # 6) 다시 풀기
    }
