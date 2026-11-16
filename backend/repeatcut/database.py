"""SQLite 연결과 DB 구조 관리.

■ 구조 버전
  DB 파일 안의 PRAGMA user_version 에 "지금 구조가 몇 번째인지"를 적어 둔다.
  서버가 켜질 때 MIGRATIONS 중 아직 적용 안 된 것만 번호 순서로 실행한다.
  → 배포 서버의 DB를 새 코드에 맞게 안전하게 올릴 수 있다.

  구조를 바꾸고 싶을 때: migrate_N 함수를 하나 더 만들고 MIGRATIONS에 (N, 함수)를 추가한다.
  (이미 적용된 번호의 함수는 고치지 않는다. 항상 새 번호를 만든다)

■ 안전장치
  - 번호 하나가 통째로 한 트랜잭션: 중간에 실패하면 그 번호는 적용 전 상태로 돌아간다.
  - 구조를 바꾸기 전에 DB 파일을 자동 백업한다. (REPEATCUT_BACKUP=0 으로 끌 수 있음)
  - DB가 코드보다 새 버전이면(예: 예전 코드로 롤백) 데이터를 건드리지 않고 시작을 멈춘다.
"""
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from .rules import DEFAULT_EXAM, clean, guess_exam_type


# ──────────────────────────────────────────────
# 연결
# ──────────────────────────────────────────────
def connect(db_path):
    """SQLite 연결 하나를 만든다."""
    folder = os.path.dirname(db_path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10)  # 다른 요청이 쓰는 중이면 10초까지 기다린다
    conn.row_factory = sqlite3.Row
    # SQLite는 이걸 켜지 않으면 외래키(paper_id, keyword_id)를 검사하지 않는다. (연결마다 켜야 함)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def session(db_path):
    """요청 하나가 쓰는 연결. 성공하면 저장(commit), 예외가 나면 되돌리고(rollback), 끝나면 닫는다.
    (sqlite3 기본 `with conn:`은 닫아 주지 않아서 연결이 쌓일 수 있다)"""
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


# ──────────────────────────────────────────────
# 구조 정의 (아래 BASE_SCHEMA는 1번 구조. 지금 구조는 migrate_3까지 적용된 모습이다)
#   users    (회원)        PK: id, email은 중복 불가(대소문자 무시)
#   sessions (로그인 상태)  PK: id, FK: user_id -> users.id, token_hash는 중복 불가
#   exams    (시험·자격증)  PK: id, name은 중복 불가(대소문자 무시)
#   papers   (문제지정보)  PK: id, FK: user_id -> users.id, exam_id -> exams.id
#   keywords (핵심키워드)  PK: id, name은 중복 불가(대소문자 무시)
#   mistakes (오답노트)    PK: id, FK: paper_id -> papers.id, keyword_id -> keywords.id
#                          image_no는 중복 불가(UNIQUE) = 이미지 고유 번호
#                          (누구의 오답인지는 papers.user_id로 안다. mistakes에는 user_id를 두지 않는다)
#   attempts (다시 푼 기록) PK: id, FK: mistake_id -> mistakes.id (오답을 지우면 같이 지워짐)
#                          같은 문제를 또 틀리면 mistakes에 새 줄을 만들지 않고 여기에 한 줄을 더한다
#                          (my_answer = 그때 고른 답, reason_type = 그때 틀린 이유)
# ──────────────────────────────────────────────
BASE_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS papers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        exam TEXT NOT NULL DEFAULT '지역농협',
        year INTEGER,
        exam_type TEXT NOT NULL DEFAULT '기출',
        round TEXT NOT NULL DEFAULT '기타',
        title TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        UNIQUE (exam, year, exam_type, round, title)
    )""",
    """CREATE TABLE IF NOT EXISTS keywords (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE COLLATE NOCASE
    )""",
    """CREATE TABLE IF NOT EXISTS mistakes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE RESTRICT,
        problem_no TEXT NOT NULL,
        page INTEGER NOT NULL,
        keyword_id INTEGER NOT NULL REFERENCES keywords(id),
        reason_type TEXT NOT NULL,
        memo TEXT NOT NULL DEFAULT '',
        image_no TEXT NOT NULL UNIQUE,
        image_path TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_mistakes_paper ON mistakes(paper_id)",
    "CREATE INDEX IF NOT EXISTS idx_mistakes_keyword ON mistakes(keyword_id)",
    "CREATE INDEX IF NOT EXISTS idx_mistakes_created_at ON mistakes(created_at)",
]


def table_exists(conn, name):
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone()
    return row is not None


def column_names(conn, table):
    return [row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def add_column_if_missing(conn, table, column, definition):
    """이미 있는 컬럼이면 건너뛴다. (CREATE TABLE IF NOT EXISTS는 기존 테이블에 컬럼을 더해주지 않는다)"""
    if column not in column_names(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


# ──────────────────────────────────────────────
# 번호가 붙은 구조 변경 (migrations)
# 모두 "이미 적용돼 있어도 다시 실행해도 안전"하게 만들어 두었다.
# (버전 번호를 도입하기 전에 만들어진 DB도 문제없이 번호를 받을 수 있게)
# ──────────────────────────────────────────────
def migrate_1_three_tables(conn):
    """1번: 문제지 / 키워드 / 오답 3개 테이블 구조.
    예전 구조(worksheet / keyword / wrong_reason이 전부 문자열인 mistakes)가 있으면 새 구조로 옮긴다.
      - 예전 테이블은 mistakes_legacy 라는 이름으로 남겨둔다 (백업용, 필요 없으면 직접 DROP)
      - 오답 id와 image_no는 그대로 가져온다"""
    columns = column_names(conn, "mistakes") if table_exists(conn, "mistakes") else []
    is_legacy = "worksheet" in columns

    if is_legacy:
        if "problem_no" not in columns:
            conn.execute("ALTER TABLE mistakes ADD COLUMN problem_no TEXT NOT NULL DEFAULT ''")
        # 예전 인덱스 이름이 새 인덱스와 겹치므로 먼저 지운다
        conn.execute("DROP INDEX IF EXISTS idx_mistakes_keyword")
        conn.execute("DROP INDEX IF EXISTS idx_mistakes_created_at")
        conn.execute("ALTER TABLE mistakes RENAME TO mistakes_legacy")

    for statement in BASE_SCHEMA:
        conn.execute(statement)

    if is_legacy:
        for row in conn.execute("SELECT * FROM mistakes_legacy ORDER BY id").fetchall():
            title = clean(row["worksheet"]) or "(이름 없음)"
            # 연도·회차는 알 수 없으니 비워둔다 (연도 NULL, 회차 '기타') → 앱에서 '문제지 수정'으로 채운다
            paper = conn.execute(
                "SELECT id FROM papers WHERE exam = ? AND year IS NULL AND exam_type = ? AND round = '기타' AND title = ?",
                (DEFAULT_EXAM, guess_exam_type(title), title),
            ).fetchone()
            if paper:
                paper_id = paper["id"]
            else:
                paper_id = conn.execute(
                    "INSERT INTO papers (exam, year, exam_type, round, title, created_at) VALUES (?, NULL, ?, '기타', ?, ?)",
                    (DEFAULT_EXAM, guess_exam_type(title), title, row["created_at"]),
                ).lastrowid

            keyword_name = clean(row["keyword"]) or "(미지정)"
            keyword = conn.execute("SELECT id FROM keywords WHERE name = ?", (keyword_name,)).fetchone()
            keyword_id = keyword["id"] if keyword else conn.execute("INSERT INTO keywords (name) VALUES (?)", (keyword_name,)).lastrowid

            conn.execute(
                """INSERT INTO mistakes
                   (id, paper_id, problem_no, page, keyword_id, reason_type, memo, image_no, image_path, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    row["id"], paper_id, row["problem_no"], row["page"], keyword_id,
                    "기타",  # 오답 이유 유형은 예전엔 없었으니 '기타', 기존 서술은 memo로 보존
                    row["wrong_reason"], row["image_no"], row["image_path"], row["created_at"],
                ),
            )


def migrate_2_answers_and_question_count(conn):
    """2번: 내가 고른 답 / 정답 (오답별), 문항 수 (문제지별)."""
    add_column_if_missing(conn, "papers", "total_questions", "INTEGER")
    add_column_if_missing(conn, "mistakes", "my_answer", "TEXT NOT NULL DEFAULT ''")
    add_column_if_missing(conn, "mistakes", "correct_answer", "TEXT NOT NULL DEFAULT ''")


def migrate_3_users_exams_attempts(conn):
    """3번: 로그인(users, sessions), 시험 종류(exams), 다시 푼 기록(attempts).
    papers는 exam(문자열) 대신 exam_id를, 그리고 주인(user_id)을 갖도록 새로 만든다.

    - 이미 있던 문제지는 user_id가 NULL(주인 없음)로 옮겨진다.
      → 처음 가입하는 회원이 그 데이터를 넘겨받는다. (repository.claim_unowned_papers)
    - 문제지 id는 그대로 유지하므로 mistakes.paper_id는 고칠 필요가 없다.
    - SQLite는 UNIQUE 조건이나 컬럼을 바꿀 수 없어서 "새 테이블 만들기 → 복사 → 예전 것 지우기 → 이름 바꾸기"로 한다.
      (이 동안 외래키 검사는 migrate()가 꺼 두고, 끝난 뒤 foreign_key_check로 다시 확인한다)"""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            nickname TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS exams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE COLLATE NOCASE,
            created_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mistake_id INTEGER NOT NULL REFERENCES mistakes(id) ON DELETE CASCADE,
            is_correct INTEGER NOT NULL CHECK (is_correct IN (0, 1)),
            attempted_at TEXT NOT NULL
        )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_attempts_mistake ON attempts(mistake_id)")

    if "exam_id" in column_names(conn, "papers"):
        return  # papers는 이미 새 구조

    now = datetime.now().isoformat(timespec="seconds")
    # 문제지에 적혀 있던 시험명을 exams로 옮긴다 (같은 이름은 한 번만)
    for row in conn.execute("SELECT DISTINCT exam FROM papers ORDER BY exam").fetchall():
        conn.execute("INSERT OR IGNORE INTO exams (name, created_at) VALUES (?, ?)", (row["exam"], now))

    conn.execute("DROP TABLE IF EXISTS papers_new")
    conn.execute(
        """CREATE TABLE papers_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id),
            exam_id INTEGER NOT NULL REFERENCES exams(id),
            year INTEGER,
            exam_type TEXT NOT NULL DEFAULT '기출',
            round TEXT NOT NULL DEFAULT '기타',
            title TEXT NOT NULL DEFAULT '',
            total_questions INTEGER,
            created_at TEXT NOT NULL,
            UNIQUE (user_id, exam_id, year, exam_type, round, title)
        )"""
    )
    conn.execute(
        """INSERT INTO papers_new (id, user_id, exam_id, year, exam_type, round, title, total_questions, created_at)
           SELECT p.id, NULL, e.id, p.year, p.exam_type, p.round, p.title, p.total_questions, p.created_at
           FROM papers p JOIN exams e ON e.name = p.exam
           ORDER BY p.id"""
    )
    copied = conn.execute("SELECT COUNT(*) FROM papers_new").fetchone()[0]
    original = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
    if copied != original:
        raise RuntimeError(f"문제지를 옮기다가 개수가 달라졌어요 (원래 {original}개, 옮긴 것 {copied}개). 구조 변경을 취소합니다.")
    conn.execute("DROP TABLE papers")
    conn.execute("ALTER TABLE papers_new RENAME TO papers")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_papers_user ON papers(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_papers_exam ON papers(exam_id)")


def migrate_4_attempt_answer_and_drop_ncs(conn):
    """4번: 다시 푼 기록에 '그때 고른 답'(my_answer) 추가, 쓰지 않는 NCS 예시 테이블 삭제."""
    add_column_if_missing(conn, "attempts", "my_answer", "TEXT NOT NULL DEFAULT ''")
    conn.execute("DROP TABLE IF EXISTS dfp_1ca648cb")  # NCS 기준정보 화면을 없애면서 같이 지운다 (예시 데이터뿐이었다)


def migrate_5_attempt_reason(conn):
    """5번: 다시 푼 기록에 '그때 틀린 이유'(reason_type) 추가. 같은 문제라도 틀릴 때마다 이유가 다를 수 있다."""
    add_column_if_missing(conn, "attempts", "reason_type", "TEXT NOT NULL DEFAULT ''")


MIGRATIONS = [
    (1, migrate_1_three_tables),
    (2, migrate_2_answers_and_question_count),
    (3, migrate_3_users_exams_attempts),
    (4, migrate_4_attempt_answer_and_drop_ncs),
    (5, migrate_5_attempt_reason),
]
LATEST_VERSION = MIGRATIONS[-1][0]


class SchemaTooNewError(RuntimeError):
    pass


def get_version(conn):
    return conn.execute("PRAGMA user_version").fetchone()[0]


def make_backup(db_path, from_version):
    """구조를 바꾸기 전에 DB 파일 전체를 옆에 복사해 둔다. (SQLite 백업 기능이라 사용 중이어도 안전)"""
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    backup_path = f"{db_path}.backup-v{from_version}-{stamp}"
    source = sqlite3.connect(db_path)
    target = sqlite3.connect(backup_path)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    return backup_path


def migrate(db_path, backup=True):
    """아직 적용 안 된 구조 변경을 순서대로 적용한다.
    (적용한 번호 목록, 백업 파일 경로 또는 None)을 돌려준다."""
    conn = connect(db_path)
    conn.isolation_level = None  # BEGIN / COMMIT을 직접 제어한다 (DDL도 트랜잭션에 묶기 위해)
    # 테이블을 새로 만들어 바꿔 끼우는 동안에는 외래키 검사를 끈다. (SQLite 공식 문서의 테이블 변경 절차)
    # 이 설정은 트랜잭션 밖에서만 바뀌므로 BEGIN 전에 해 둔다. 대신 번호마다 COMMIT 직전에 직접 검사한다.
    conn.execute("PRAGMA foreign_keys = OFF")
    applied, backup_path = [], None
    try:
        current = get_version(conn)
        if current > LATEST_VERSION:
            raise SchemaTooNewError(
                f"DB 구조 버전({current})이 이 코드({LATEST_VERSION})보다 새로워요. 최신 코드로 실행해 주세요."
            )
        pending = [(number, fn) for number, fn in MIGRATIONS if number > current]
        if not pending:
            return applied, backup_path

        has_data = table_exists(conn, "mistakes") or table_exists(conn, "papers")
        if backup and has_data:
            backup_path = make_backup(db_path, current)

        for number, fn in pending:
            # 서버를 여러 개(worker) 동시에 켜도 한 곳만 구조를 바꾸도록, 시작하자마자 쓰기 잠금을 잡는다.
            # 잠금을 얻은 뒤 번호를 다시 확인해서, 다른 서버가 이미 적용했다면 건너뛴다.
            conn.execute("BEGIN IMMEDIATE")
            try:
                if get_version(conn) >= number:
                    conn.execute("COMMIT")
                    continue
                fn(conn)
                broken = conn.execute("PRAGMA foreign_key_check").fetchall()
                if broken:
                    raise RuntimeError(f"구조 변경 {number}번 뒤에 연결이 끊긴 데이터가 {len(broken)}건 있어요. 변경을 취소합니다.")
                conn.execute(f"PRAGMA user_version = {int(number)}")
                conn.execute("COMMIT")
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
            applied.append(number)
        return applied, backup_path
    finally:
        conn.close()


def enable_wal(db_path):
    """여러 요청이 동시에 읽고 쓸 때 덜 막히도록 WAL 모드를 켠다. (DB 파일에 한 번 저장되면 유지됨)"""
    conn = connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
    finally:
        conn.close()
