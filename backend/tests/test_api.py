"""로그인·회원별 데이터 분리·같은 문제 다시 틀림 기록·DB 구조 변경(2번→5번) 테스트.

실행 (프로젝트 루트에서):
    pip install pytest httpx
    pytest backend/tests -v
  pytest 없이도 된다:  python backend/tests/test_api.py

- 임시 폴더에 "로그인 기능이 생기기 전(구조 2번)" 모양의 DB를 만들고, 서버를 켜서 5번으로 올라가는지부터 확인한다.
- 실제 data/app.db는 건드리지 않는다.
- 테스트 함수는 위에서 아래로 순서대로 실행되는 것을 전제로 한다. (앞에서 가입한 회원을 뒤에서 쓴다)
"""
import os
import shutil
import sqlite3
import sys
import tempfile

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

# main.py는 import될 때 환경변수를 읽어 DB를 준비하므로, import 전에 임시 경로를 정해 둔다.
TEMP_DIR = tempfile.mkdtemp(prefix="repeatcut-test-")
DB_PATH = os.path.join(TEMP_DIR, "app.db")
os.environ["REPEATCUT_DB"] = DB_PATH
os.environ["REPEATCUT_UPLOAD_DIR"] = os.path.join(TEMP_DIR, "uploads")
os.environ["REPEATCUT_STORAGE"] = "local"
os.environ.pop("REPEATCUT_GEMINI_API_KEY", None)  # 테스트는 실제 Gemini를 부르지 않는다 (키 없음 = 규칙 기반 추천)
os.environ.pop("GEMINI_API_KEY", None)

from repeatcut import auth, database  # noqa: E402

# 1x1 PNG (이미지 업로드용)
TINY_PNG = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def build_old_database():
    """구조 2번(로그인 없음) DB를 만들고 문제지 2개, 오답 3개를 넣는다."""
    conn = database.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = OFF")
    database.migrate_1_three_tables(conn)
    database.migrate_2_answers_and_question_count(conn)
    conn.execute("PRAGMA user_version = 2")
    conn.execute(
        "INSERT INTO papers (id, exam, year, exam_type, round, title, total_questions, created_at) VALUES "
        "(1, '지역농협', 2025, '기출', '상반기', '', 60, '2026-01-01T10:00:00'), "
        "(2, '지역농협', 2025, '모의고사', '1회차', '', NULL, '2026-01-02T10:00:00')"
    )
    conn.execute("INSERT INTO keywords (id, name) VALUES (1, '농도'), (2, '일률')")
    conn.execute("CREATE TABLE dfp_1ca648cb (NCS_CL_CD TEXT)")  # 예전 NCS 예시 테이블 (4번에서 지워져야 한다)
    conn.execute(
        "INSERT INTO mistakes (id, paper_id, problem_no, page, keyword_id, reason_type, memo, image_no, image_path, created_at) VALUES "
        "(1, 1, '12', 3, 1, '계산실수', '', 'IMG-OLD-1', 'old-1.png', '2026-01-03T10:00:00'), "
        "(2, 1, '15', 4, 2, '시간 부족', '', 'IMG-OLD-2', 'old-2.png', '2026-01-04T10:00:00'), "
        "(3, 2, '7', 2, 1, '계산실수', '', 'IMG-OLD-3', 'old-3.png', '2026-01-05T10:00:00')"
    )
    conn.commit()
    conn.close()


build_old_database()

from fastapi.testclient import TestClient  # noqa: E402
import main  # noqa: E402  (여기서 구조 5번으로 올라간다)

client = TestClient(main.app)
state = {}  # 테스트끼리 넘겨 쓰는 값 (토큰, id)


def headers(name):
    return {"Authorization": f"Bearer {state[name]}"}


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ──────────────────────────────────────────────
# DB 구조 변경
# ──────────────────────────────────────────────
def test_migration_keeps_old_data():
    conn = db()
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 5
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"users", "sessions", "exams", "papers", "mistakes", "keywords", "attempts"} <= tables
    assert "papers_new" not in tables and "dfp_1ca648cb" not in tables
    attempt_columns = [row[1] for row in conn.execute("PRAGMA table_info(attempts)")]
    assert "my_answer" in attempt_columns and "reason_type" in attempt_columns
    paper_columns = [row[1] for row in conn.execute("PRAGMA table_info(papers)")]
    assert "exam_id" in paper_columns and "user_id" in paper_columns and "exam" not in paper_columns
    # 개수와 id가 그대로이고, 시험명은 exams로 옮겨졌다
    assert [row[0] for row in conn.execute("SELECT id FROM papers ORDER BY id")] == [1, 2]
    assert conn.execute("SELECT COUNT(*) FROM mistakes").fetchone()[0] == 3
    assert [row[0] for row in conn.execute("SELECT name FROM exams")] == ["지역농협"]
    assert conn.execute("SELECT total_questions FROM papers WHERE id = 1").fetchone()[0] == 60
    # 아직 가입한 사람이 없으니 주인이 없다
    assert conn.execute("SELECT COUNT(*) FROM papers WHERE user_id IS NOT NULL").fetchone()[0] == 0
    # 오답 → 문제지 연결이 끊기지 않았다
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    # 구조를 바꾸기 전에 백업 파일을 만들었다
    assert any(name.startswith("app.db.backup-v2-") for name in os.listdir(TEMP_DIR))
    conn.close()


def test_migration_is_safe_to_run_again():
    applied, _ = database.migrate(DB_PATH)
    assert applied == []
    conn = database.connect(DB_PATH)
    database.migrate_3_users_exams_attempts(conn)  # 함수를 직접 한 번 더 불러도 데이터가 그대로
    database.migrate_4_attempt_answer_and_drop_ncs(conn)
    database.migrate_5_attempt_reason(conn)
    assert conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 2
    conn.rollback()
    conn.close()


# ──────────────────────────────────────────────
# 로그인
# ──────────────────────────────────────────────
def test_login_is_required():
    for path in ["/api/papers", "/api/mistakes", "/api/mistakes/trend", "/api/stats", "/api/keywords",
                 "/api/exams", "/api/mistakes/1/image", "/api/mistakes/1/attempts", "/api/auth/me"]:
        assert client.get(path).status_code == 401, path
    assert client.get(path, headers={"Authorization": "Bearer wrong-token"}).status_code == 401
    assert client.delete("/api/mistakes/1").status_code == 401
    assert client.post("/api/papers", json={"year": 2025}).status_code == 401
    # 로그인 없이 되는 것
    assert client.get("/api/health").json()["schema_version"] == 5
    assert client.get("/api/options").status_code == 200
    assert client.get("/api/ncs-units").status_code == 404  # NCS 기준정보는 없앴다
    assert client.get("/api/mistakes/lookup?paper_id=1&problem_no=12").status_code == 401


def test_register_checks_input():
    assert client.post("/api/auth/register", json={"email": "not-an-email", "password": "password1"}).status_code == 400
    assert client.post("/api/auth/register", json={"email": "a@example.com", "password": "short"}).status_code == 400
    assert client.post("/api/auth/register", json={"email": "a@example.com", "password": "x" * 101}).status_code == 400
    assert client.post("/api/auth/register", json={"email": "a@example.com", "password": "password1", "nickname": "가" * 21}).status_code == 400
    assert db().execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0


def test_first_user_takes_over_old_data():
    response = client.post("/api/auth/register", json={"email": "A@Example.com ", "password": "password-a", "nickname": "진희"})
    assert response.status_code == 201
    body = response.json()
    assert body["user"] == {"id": body["user"]["id"], "email": "a@example.com", "nickname": "진희"}
    assert body["claimed_papers"] == 2
    state["a"] = body["token"]
    assert len(client.get("/api/papers", headers=headers("a")).json()) == 2
    mistakes = client.get("/api/mistakes", headers=headers("a")).json()
    assert len(mistakes) == 3
    assert mistakes[0]["exam"] == "지역농협" and mistakes[0]["attempt_count"] == 0 and mistakes[0]["last_is_correct"] is None
    assert client.get("/api/stats", headers=headers("a")).json()["total"] == 3


def test_password_and_token_are_not_stored_as_is():
    conn = db()
    stored = conn.execute("SELECT password_hash FROM users WHERE email = 'a@example.com'").fetchone()[0]
    assert stored.startswith("pbkdf2_sha256$") and "password-a" not in stored
    token_hashes = [row[0] for row in conn.execute("SELECT token_hash FROM sessions")]
    assert state["a"] not in token_hashes and auth.hash_token(state["a"]) in token_hashes
    conn.close()


def test_duplicate_email_and_wrong_password():
    assert client.post("/api/auth/register", json={"email": "a@example.com", "password": "password-x"}).status_code == 409
    assert client.post("/api/auth/login", json={"email": "a@example.com", "password": "wrong-password"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "password-a"}).status_code == 401


def test_login_and_me():
    response = client.post("/api/auth/login", json={"email": "a@example.com", "password": "password-a"})
    assert response.status_code == 200
    state["a2"] = response.json()["token"]
    assert state["a2"] != state["a"]
    assert client.get("/api/auth/me", headers=headers("a2")).json()["email"] == "a@example.com"
    assert "password_hash" not in response.json()["user"]


def test_study_advice_api():
    assert client.post("/api/stats/advice").status_code == 401
    a = headers("a")
    # API 키가 없으면 규칙으로 만든 추천
    result = client.post("/api/stats/advice", headers=a).json()
    assert result["source"] == "rule" and result["advice"]["weak_points"][0]["title"] == "#농도"
    assert client.post("/api/stats/advice?paper_id=999", headers=a).status_code == 404
    # Gemini를 가짜로 바꿔서: 성공 → 같은 통계는 캐시 → 실패하면 규칙 기반 (실제 호출 없음)
    calls = []

    def fake_gemini(api_key, model, prompt, timeout_seconds):
        calls.append(prompt)
        return '{"summary": "요약이에요.", "weak_points": [], "plan": ["하나", "둘"], "today": "오늘 할 일"}'

    original_settings, original_caller = main.settings, main.gemini_caller
    try:
        main.settings = main.settings.__class__(**{**main.settings.__dict__, "gemini_api_key": "test-key"})
        main.gemini_caller = fake_gemini
        first = client.post("/api/stats/advice", headers=a).json()
        assert first["source"] == "gemini" and first["cached"] is False and first["advice"]["plan"] == ["하나", "둘"]
        assert client.post("/api/stats/advice", headers=a).json()["cached"] is True and len(calls) == 1
        assert "a@example.com" not in calls[0] and "test-key" not in calls[0]  # 계정 정보와 키는 보내지 않는다
        only_paper = client.post("/api/stats/advice?paper_id=2", headers=a).json()  # 오답 1개뿐인 문제지
        assert only_paper["source"] == "none" and len(calls) == 1

        def failing(api_key, model, prompt, timeout_seconds):
            raise main.advice.GeminiError("rate_limit")

        main.gemini_caller = failing
        main.advice_cache.clear()
        fallback = client.post("/api/stats/advice", headers=a).json()
        assert fallback["source"] == "rule" and "한도" in fallback["notice"] and fallback["advice"]["plan"]
    finally:
        main.settings, main.gemini_caller = original_settings, original_caller
        main.advice_cache.clear()


# ──────────────────────────────────────────────
# 회원별 데이터 분리
# ──────────────────────────────────────────────
def test_second_user_starts_empty():
    response = client.post("/api/auth/register", json={"email": "b@example.com", "password": "password-b"})
    assert response.status_code == 201 and response.json()["claimed_papers"] == 0
    state["b"] = response.json()["token"]
    assert client.get("/api/papers", headers=headers("b")).json() == []
    assert client.get("/api/mistakes", headers=headers("b")).json() == []
    assert client.get("/api/mistakes/trend", headers=headers("b")).json() == []
    assert client.get("/api/keywords", headers=headers("b")).json() == []
    assert client.get("/api/exams", headers=headers("b")).json() == []
    stats = client.get("/api/stats", headers=headers("b")).json()
    assert stats["total"] == 0 and stats["papers"] == [] and stats["keywords"] == []


def test_user_cannot_touch_other_users_data():
    b = headers("b")
    mistake_body = {"paper_id": 1, "problem_no": "1", "page": 1, "keyword": "농도", "reason_type": "계산실수"}
    paper_body = {"exam": "지역농협", "year": 2024, "exam_type": "기출", "round": "하반기"}
    assert client.get("/api/mistakes/1/image", headers=b).status_code == 404
    assert client.put("/api/mistakes/1", json=mistake_body, headers=b).status_code == 404
    assert client.delete("/api/mistakes/1", headers=b).status_code == 404
    assert client.get("/api/mistakes/1/attempts", headers=b).status_code == 404
    assert client.post("/api/mistakes/1/attempts", json={"is_correct": True}, headers=b).status_code == 404
    assert client.get("/api/stats?paper_id=1", headers=b).status_code == 404
    assert client.put("/api/papers/1", json=paper_body, headers=b).status_code == 404
    assert client.delete("/api/papers/2", headers=b).status_code == 404
    # 남의 문제지에 내 오답을 붙일 수도 없다
    assert client.post("/api/mistakes", json={**mistake_body, "image_data": TINY_PNG}, headers=b).status_code == 404
    # A의 데이터는 그대로
    conn = db()
    assert conn.execute("SELECT COUNT(*) FROM mistakes").fetchone()[0] == 3
    assert conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0
    assert conn.execute("SELECT year FROM papers WHERE id = 1").fetchone()[0] == 2025
    conn.close()


def test_same_paper_fields_are_separate_per_user():
    body = {"exam": "지역농협", "year": 2025, "exam_type": "기출", "round": "상반기"}
    mine = client.post("/api/papers", json=body, headers=headers("a"))
    assert mine.status_code == 200 and mine.json()["id"] == 1  # A는 이미 있는 문제지를 돌려받는다
    theirs = client.post("/api/papers", json=body, headers=headers("b"))
    assert theirs.status_code == 201 and theirs.json()["id"] not in (1, 2)  # B는 자기 문제지가 새로 생긴다
    state["b_paper"] = theirs.json()["id"]
    assert theirs.json()["exam"] == "지역농협" and theirs.json()["display_title"] == "2025 지역농협 상반기"
    assert db().execute("SELECT COUNT(*) FROM exams").fetchone()[0] == 1  # 시험명은 한 줄을 같이 쓴다


def test_create_mistake_with_image():
    body = {"paper_id": state["b_paper"], "problem_no": "9", "page": 5, "keyword": "농도", "reason_type": "개념이해부족",
            "my_answer": "2", "correct_answer": "4", "image_data": TINY_PNG}
    response = client.post("/api/mistakes", json=body, headers=headers("b"))
    assert response.status_code == 201
    state["b_mistake"] = response.json()["id"]
    image = client.get(f"/api/mistakes/{state['b_mistake']}/image", headers=headers("b"))
    assert image.status_code == 200 and image.content.startswith(b"\x89PNG")
    assert client.get(f"/api/mistakes/{state['b_mistake']}/image", headers=headers("a")).status_code == 404
    assert client.get(f"/api/mistakes/{state['b_mistake']}/image").status_code == 401
    # 같은 키워드 '농도'를 A도 쓰지만, 각자 자기 오답 수만 센다
    assert client.get("/api/keywords", headers=headers("b")).json() == [{"id": 1, "name": "농도", "count": 1}]
    assert client.get("/api/keywords", headers=headers("a")).json()[0] == {"id": 1, "name": "농도", "count": 2}
    assert len(client.get("/api/mistakes", headers=headers("a")).json()) == 3


def test_update_mistake_can_replace_image():
    mid = state["b_mistake"]
    row = db().execute("SELECT image_path, image_no FROM mistakes WHERE id = ?", (mid,)).fetchone()
    old_path, old_no = row["image_path"], row["image_no"]
    body = {"paper_id": state["b_paper"], "problem_no": "9", "page": 5, "keyword": "농도", "reason_type": "개념이해부족",
            "my_answer": "2", "correct_answer": "4"}
    # 이미지 없이 수정하면 이미지는 그대로
    assert client.put(f"/api/mistakes/{mid}", json=body, headers=headers("b")).status_code == 200
    assert db().execute("SELECT image_path FROM mistakes WHERE id = ?", (mid,)).fetchone()["image_path"] == old_path
    # 이상한 이미지는 거절하고 기존 이미지를 지키지 않고 그대로 둔다
    bad = client.put(f"/api/mistakes/{mid}", json={**body, "image_data": "data:image/png;base64,AAAA"}, headers=headers("b"))
    assert bad.status_code == 400
    assert db().execute("SELECT image_path FROM mistakes WHERE id = ?", (mid,)).fetchone()["image_path"] == old_path
    # 새 이미지로 바꾸면 파일이 바뀌고 이미지 번호는 그대로
    ok = client.put(f"/api/mistakes/{mid}", json={**body, "image_data": TINY_PNG}, headers=headers("b"))
    assert ok.status_code == 200
    row = db().execute("SELECT image_path, image_no FROM mistakes WHERE id = ?", (mid,)).fetchone()
    assert row["image_path"] != old_path and row["image_no"] == old_no
    assert client.get(f"/api/mistakes/{mid}/image", headers=headers("b")).content.startswith(b"\x89PNG")
    # 남의 오답 이미지는 바꿀 수 없다
    assert client.put(f"/api/mistakes/{mid}", json={**body, "image_data": TINY_PNG}, headers=headers("a")).status_code == 404


def test_filter_mistakes_by_paper():
    a = headers("a")
    # 문제지별로 나눠 센 합계가 전체와 같다
    counts = [len(client.get(f"/api/mistakes?paper_id={pid}", headers=a).json()) for pid in (1, 2)]
    assert sum(counts) == 3
    only = client.get(f"/api/mistakes?paper_id=1", headers=a).json()
    assert only and all(item["paper_id"] == 1 for item in only)
    # B의 문제지에는 B의 오답만 있고, A가 B의 문제지 번호를 넣어도 빈 목록이다
    mine = client.get(f"/api/mistakes?paper_id={state['b_paper']}", headers=headers("b")).json()
    assert [item["id"] for item in mine] == [state["b_mistake"]]
    assert client.get(f"/api/mistakes?paper_id={state['b_paper']}", headers=a).json() == []
    # 키워드 검색과 같이 쓸 수 있다
    assert client.get("/api/mistakes?paper_id=1&keyword=없는키워드", headers=a).json() == []


# ──────────────────────────────────────────────
# 같은 문제는 한 번만 등록
# ──────────────────────────────────────────────
def test_same_problem_is_registered_once():
    a, b = headers("a"), headers("b")
    found = client.get("/api/mistakes/lookup?paper_id=1&problem_no=12", headers=a).json()["mistake"]
    assert found["id"] == 1 and found["wrong_total"] == 1 and found["keyword"] == "농도"
    assert client.get("/api/mistakes/lookup?paper_id=1&problem_no=99", headers=a).json()["mistake"] is None
    assert client.get("/api/mistakes/lookup?paper_id=2&problem_no=12", headers=a).json()["mistake"] is None  # 다른 문제지
    assert client.get("/api/mistakes/lookup?paper_id=1&problem_no=12", headers=b).json()["mistake"] is None  # 남의 문제지
    # 같은 문제지의 같은 번호를 또 등록하면 409, 오답 수는 그대로
    body = {"paper_id": 1, "problem_no": " 12 ", "page": 3, "keyword": "농도", "reason_type": "계산실수", "image_data": TINY_PNG}
    assert client.post("/api/mistakes", json=body, headers=a).status_code == 409
    assert db().execute("SELECT COUNT(*) FROM mistakes WHERE paper_id = 1").fetchone()[0] == 2
    assert len(os.listdir(os.environ["REPEATCUT_UPLOAD_DIR"])) == 1  # 거절된 요청의 이미지는 저장되지 않는다 (B의 1장만 있음)
    # 수정으로 번호를 다른 오답과 같게 만들 수도 없다. 번호를 안 바꾸는 수정은 된다.
    edit = {"paper_id": 1, "problem_no": "12", "page": 4, "keyword": "일률", "reason_type": "시간 부족"}
    assert client.put("/api/mistakes/2", json=edit, headers=a).status_code == 409
    assert client.put("/api/mistakes/1", json={**edit, "keyword": "농도", "memo": "메모만 수정"}, headers=a).status_code == 200
    # 다른 회원은 자기 문제지에 같은 번호를 따로 등록할 수 있다 (B의 9번은 이미 있음 → B에게만 409)
    b_body = {**body, "paper_id": state["b_paper"], "problem_no": "9"}
    assert client.post("/api/mistakes", json=b_body, headers=b).status_code == 409


# ──────────────────────────────────────────────
# 시험명
# ──────────────────────────────────────────────
def test_exam_names():
    a = headers("a")
    body = {"exam": "컴퓨터활용능력 1급", "year": 2025, "exam_type": "모의고사", "round": "1회차"}
    updated = client.put("/api/papers/2", json=body, headers=a)
    assert updated.status_code == 200 and updated.json()["exam"] == "컴퓨터활용능력 1급"
    assert [item["name"] for item in client.get("/api/exams", headers=a).json()] == ["지역농협", "컴퓨터활용능력 1급"]
    assert [item["name"] for item in client.get("/api/exams", headers=headers("b")).json()] == ["지역농협"]
    # 내 다른 문제지와 똑같아지면 409
    same = {"exam": "지역농협", "year": 2025, "exam_type": "기출", "round": "상반기"}
    assert client.put("/api/papers/2", json=same, headers=a).status_code == 409
    # 원래대로 돌리면 안 쓰는 시험명은 정리된다
    back = {"exam": "지역농협", "year": 2025, "exam_type": "모의고사", "round": "1회차"}
    assert client.put("/api/papers/2", json=back, headers=a).status_code == 200
    assert [row[0] for row in db().execute("SELECT name FROM exams")] == ["지역농협"]


# ──────────────────────────────────────────────
# 다시 푼 기록
# ──────────────────────────────────────────────
def test_attempts():
    a = headers("a")
    first = client.post("/api/mistakes/1/attempts", json={"is_correct": False, "my_answer": "3", "reason_type": "개념이해부족"}, headers=a)
    assert first.status_code == 201 and first.json()["attempts"][0]["reason_type"] == "개념이해부족"
    assert client.post("/api/mistakes/1/attempts", json={"is_correct": False, "reason_type": "없는 이유"}, headers=a).status_code == 400
    assert first.json()["mistake"]["attempt_count"] == 1 and first.json()["mistake"]["last_is_correct"] == 0
    assert first.json()["mistake"]["wrong_total"] == 2 and first.json()["attempts"][0]["my_answer"] == "3"
    client.post("/api/mistakes/1/attempts", json={"is_correct": False, "my_answer": "3"}, headers=a)
    third = client.post("/api/mistakes/1/attempts", json={"is_correct": True}, headers=a).json()
    assert third["mistake"]["attempt_count"] == 3 and third["mistake"]["correct_count"] == 1
    assert third["mistake"]["last_is_correct"] == 1 and third["mistake"]["wrong_total"] == 3
    assert [item["is_correct"] for item in third["attempts"]] == [1, 0, 0]  # 최근 것이 맨 위
    client.post("/api/mistakes/2/attempts", json={"is_correct": False}, headers=a)
    assert client.post("/api/mistakes/1/attempts", json={}, headers=a).status_code == 422  # is_correct 빠짐

    retry = client.get("/api/stats", headers=a).json()["retry"]
    assert retry["attempts"] == 4 and retry["correct"] == 1 and retry["correct_rate"] == 0.25
    assert retry["solved"] == 1 and retry["still_wrong"] == 1 and retry["not_retried"] == 1
    assert [(item["mistake_id"], item["wrong_count"], item["attempt_count"]) for item in retry["repeat_wrong"]] == [(1, 2, 3), (2, 1, 1)]
    assert retry["repeat_wrong"][0]["paper_title"] == "2025 지역농협 상반기"
    assert retry["repeat_wrong"][0]["wrong_total"] == 3 and retry["repeat_wrong"][0]["wrong_answers"] == ["3", "3"]
    assert retry["repeat_wrong"][1]["wrong_answers"] == []
    # 틀린 이유 흐름: 처음 등록할 때의 이유 → 또 틀렸을 때의 이유 (이유를 안 넣은 기록은 빠진다)
    assert retry["repeat_wrong"][0]["wrong_reasons"] == ["시간 부족", "개념이해부족"]
    assert retry["repeat_wrong"][1]["wrong_reasons"] == ["시간 부족"]
    # '오답 이유별'은 처음 등록 3건 + 이유를 적은 또 틀림 1건 = 4건 기준
    stats = client.get("/api/stats", headers=a).json()
    reason_counts = {item["reason_type"]: item["count"] for item in stats["reasons"]}
    assert stats["reason_total"] == 4 and stats["total"] == 3
    assert reason_counts["시간 부족"] == 2 and reason_counts["계산실수"] == 1 and reason_counts["개념이해부족"] == 1
    assert [item["ratio"] for item in stats["reasons"] if item["reason_type"] == "시간 부족"] == [0.5]
    # 키워드 x 이유 표에도 들어간다 (오답 1의 키워드는 '농도')
    nongdo = [row for row in stats["keyword_reasons"]["rows"] if row["name"] == "농도"][0]
    assert nongdo["counts"]["개념이해부족"] == 1 and nongdo["total"] == 3
    # '내가 자주 고른 오답 번호'에 또 틀릴 때 고른 답도 들어간다
    my_answers = client.get("/api/stats", headers=a).json()["answers"]["my_answer"]
    assert my_answers["sample"] == 2 and my_answers["items"][2] == {"answer": "3", "count": 2}
    # 문제지 2만 보면 다시 푼 기록이 없다
    only_paper_2 = client.get("/api/stats?paper_id=2", headers=a).json()["retry"]
    assert only_paper_2["attempts"] == 0 and only_paper_2["correct_rate"] is None and only_paper_2["not_retried"] == 1
    # B의 통계에는 A의 기록이 섞이지 않는다
    b_retry = client.get("/api/stats", headers=headers("b")).json()["retry"]
    assert b_retry["attempts"] == 0 and b_retry["not_retried"] == 1 and b_retry["repeat_wrong"] == []


def test_wrong_again_answer_rules():
    b = headers("b")
    path = f"/api/mistakes/{state['b_mistake']}/attempts"  # 처음 고른 답 2, 정답 4
    assert client.post(path, json={"is_correct": False, "my_answer": "4"}, headers=b).status_code == 400  # 정답과 같은 답
    assert client.post(path, json={"is_correct": False, "my_answer": "x" * 21}, headers=b).status_code == 400
    wrong = client.post(path, json={"is_correct": False, "my_answer": "2"}, headers=b).json()
    assert wrong["mistake"]["wrong_total"] == 2 and wrong["attempts"][0]["my_answer"] == "2"
    right = client.post(path, json={"is_correct": True, "my_answer": "4", "reason_type": "계산실수"}, headers=b).json()
    assert right["attempts"][0]["my_answer"] == "" and right["attempts"][0]["reason_type"] == ""  # 맞혔을 때는 답·이유를 기록하지 않는다
    stats = client.get("/api/stats", headers=b).json()
    assert stats["answers"]["my_answer"]["items"][1] == {"answer": "2", "count": 2}  # 등록 때 1번 + 또 틀릴 때 1번
    assert stats["retry"]["repeat_wrong"][0]["wrong_answers"] == ["2", "2"] and stats["retry"]["repeat_wrong"][0]["correct_answer"] == "4"
    assert stats["total"] == 1  # 오답 수는 늘지 않는다


def test_delete_attempt_and_cascade():
    a = headers("a")
    attempts = client.get("/api/mistakes/1/attempts", headers=a).json()
    newest = attempts[0]["id"]
    assert client.delete(f"/api/mistakes/2/attempts/{newest}", headers=a).status_code == 404  # 다른 오답의 기록
    assert client.delete(f"/api/mistakes/1/attempts/{newest}", headers=headers("b")).status_code == 404
    removed = client.delete(f"/api/mistakes/1/attempts/{newest}", headers=a)
    assert removed.status_code == 200 and removed.json()["mistake"]["attempt_count"] == 2
    assert removed.json()["mistake"]["last_is_correct"] == 0
    # 오답을 지우면 다시 푼 기록도 같이 지워진다
    assert client.delete("/api/mistakes/1", headers=a).status_code == 200
    conn = db()
    assert conn.execute("SELECT COUNT(*) FROM attempts WHERE mistake_id = 1").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM attempts WHERE mistake_id = 2").fetchone()[0] == 1  # 다른 오답의 기록은 남아 있다
    conn.close()


def test_paper_rules_still_work():
    a = headers("a")
    assert client.delete("/api/papers/1", headers=a).status_code == 409  # 오답이 남아 있는 문제지
    assert client.delete("/api/mistakes/2", headers=a).status_code == 200
    assert client.delete("/api/papers/1", headers=a).status_code == 200
    assert [paper["id"] for paper in client.get("/api/papers", headers=a).json()] == [2]


# ──────────────────────────────────────────────
# 로그아웃 / 만료
# ──────────────────────────────────────────────
def test_page_is_optional_but_problem_no_is_required():
    paper = client.post("/api/papers", json={"exam": "TMP", "year": 2025, "exam_type": "기출", "round": "기타"}, headers=headers("b")).json()
    base = {"paper_id": paper["id"], "keyword": "조인", "reason_type": "개념이해부족", "image_data": TINY_PNG}
    # 페이지 없이도 등록된다 (0 = 입력 안 함)
    made = client.post("/api/mistakes", json={**base, "problem_no": "3"}, headers=headers("b"))
    assert made.status_code == 201 and made.json()["page"] == 0
    # 같은 문제 판정은 문제지 + 문제 번호 기준이라 페이지가 없어도 그대로 동작한다
    again = client.post("/api/mistakes", json={**base, "problem_no": "3"}, headers=headers("b"))
    assert again.status_code in (200, 409) and len(client.get(f"/api/mistakes?paper_id={paper['id']}", headers=headers("b")).json()) == 1
    # 문제 번호는 여전히 필수, 페이지는 음수만 막는다
    assert client.post("/api/mistakes", json={**base, "problem_no": "  "}, headers=headers("b")).status_code == 400
    assert client.post("/api/mistakes", json={**base, "problem_no": "4", "page": -1}, headers=headers("b")).status_code == 400
    # 수정에서도 페이지를 비울 수 있다
    mid = made.json()["id"]
    upd = client.put(f"/api/mistakes/{mid}", json={"paper_id": paper["id"], "problem_no": "3", "page": 7, "keyword": "조인", "reason_type": "개념이해부족"}, headers=headers("b"))
    assert upd.status_code == 200 and upd.json()["page"] == 7
    upd = client.put(f"/api/mistakes/{mid}", json={"paper_id": paper["id"], "problem_no": "3", "keyword": "조인", "reason_type": "개념이해부족"}, headers=headers("b"))
    assert upd.status_code == 200 and upd.json()["page"] == 0
    state["tmp_paper"] = paper["id"]
    state["tmp_exam"] = paper["exam_id"]


def test_delete_exam_with_mistakes_needs_confirmation():
    exam_id = state["tmp_exam"]
    assert client.delete(f"/api/exams/{exam_id}", headers=headers("a")).status_code == 404  # 남의 시험
    refused = client.delete(f"/api/exams/{exam_id}", headers=headers("b"))
    assert refused.status_code == 409 and "오답 1개" in refused.json()["detail"]
    assert len(client.get("/api/papers", headers=headers("b")).json()) > 0
    ok = client.delete(f"/api/exams/{exam_id}?with_mistakes=true", headers=headers("b"))
    assert ok.status_code == 200 and ok.json()["mistakes"] == 1
    assert db().execute("SELECT COUNT(*) FROM exams WHERE id = ?", (exam_id,)).fetchone()[0] == 0
    assert db().execute("SELECT COUNT(*) FROM mistakes WHERE paper_id = ?", (state["tmp_paper"],)).fetchone()[0] == 0
    assert not [p for p in client.get("/api/papers", headers=headers("b")).json() if p["exam"] == "TMP"]


def test_rename_exam_fixes_capital_letters():
    lower = client.post("/api/papers", json={"exam": "sqld", "year": 2025, "exam_type": "기출", "round": "기타"}, headers=headers("b")).json()
    exam_id = lower["exam_id"]
    # 나만 쓰는 시험이면 이름 자체가 고쳐진다 (대소문자만 바꿔도 된다)
    assert client.put(f"/api/exams/{exam_id}", json={"name": " SQLD "}, headers=headers("b")).json() == {"id": exam_id, "name": "SQLD"}
    assert [p["exam"] for p in client.get("/api/papers", headers=headers("b")).json() if p["exam_id"] == exam_id] == ["SQLD"]
    assert client.put(f"/api/exams/{exam_id}", json={"name": "   "}, headers=headers("b")).status_code == 400
    assert client.put(f"/api/exams/{exam_id}", json={"name": "SQLD"}, headers=headers("a")).status_code == 404

    # 다른 회원도 같은 시험을 쓰고 있으면, 내 것만 새 이름으로 옮기고 남의 것은 그대로 둔다
    other = client.post("/api/papers", json={"exam": "sqld", "year": 2025, "exam_type": "기출", "round": "기타"}, headers=headers("a")).json()
    assert other["exam_id"] == exam_id  # 대소문자 무시로 같은 시험 한 줄을 같이 쓴다
    assert client.put(f"/api/exams/{exam_id}", json={"name": "sqld"}, headers=headers("b")).status_code == 409  # 대소문자만 바꾸는 건 남의 이름까지 바뀌므로 막는다
    moved = client.put(f"/api/exams/{exam_id}", json={"name": "SQLD 자격증"}, headers=headers("b")).json()
    assert moved["id"] != exam_id
    assert [p["exam"] for p in client.get("/api/papers", headers=headers("b")).json() if p["id"] == lower["id"]] == ["SQLD 자격증"]
    assert [p["exam"] for p in client.get("/api/papers", headers=headers("a")).json() if p["id"] == other["id"]] == ["SQLD"]

    # 이미 있는 시험 이름으로 바꾸면 합쳐진다. 같은 문제지가 겹치면 거절한다
    merge = client.put(f"/api/exams/{moved['id']}", json={"name": "지역농협"}, headers=headers("b"))
    assert merge.status_code == 200 and merge.json()["id"] == 1
    assert client.delete(f"/api/exams/{other['exam_id']}", headers=headers("a")).status_code == 200  # 정리
    assert db().execute("SELECT COUNT(*) FROM exams WHERE name = 'SQLD'").fetchone()[0] == 0


def test_logout_and_expiry():
    assert client.post("/api/auth/logout", headers=headers("a2")).status_code == 200
    assert client.get("/api/auth/me", headers=headers("a2")).status_code == 401  # 로그아웃한 토큰
    assert client.get("/api/auth/me", headers=headers("a")).status_code == 200  # 다른 기기의 로그인은 유지
    conn = db()
    conn.execute("UPDATE sessions SET expires_at = '2000-01-01T00:00:00' WHERE token_hash = ?", (auth.hash_token(state["b"]),))
    conn.commit()
    conn.close()
    assert client.get("/api/papers", headers=headers("b")).status_code == 401  # 기한이 지난 토큰
    # 다시 로그인하면 기한 지난 로그인 상태는 정리된다
    assert client.post("/api/auth/login", json={"email": "b@example.com", "password": "password-b"}).status_code == 200
    assert db().execute("SELECT COUNT(*) FROM sessions WHERE expires_at < '2001'").fetchone()[0] == 0


def teardown_module(module=None):
    shutil.rmtree(TEMP_DIR, ignore_errors=True)


if __name__ == "__main__":
    tests = [(name, fn) for name, fn in list(globals().items()) if name.startswith("test_") and callable(fn)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"통과  {name}")
        except Exception as error:  # noqa: BLE001
            failed += 1
            print(f"실패  {name}: {type(error).__name__}: {error}")
    teardown_module()
    print(f"\n{len(tests) - failed}/{len(tests)} 통과")
    sys.exit(1 if failed else 0)
