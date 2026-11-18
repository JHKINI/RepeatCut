"""RepeatCut API 서버.

실행:  cd backend && uvicorn main:app --reload --port 8000
       (프로젝트 루트에서 `uvicorn backend.main:app` 으로 켜도 된다)

이 파일은 "요청을 받고 → 입력을 검사하고 → repository(SQL)를 부르고 → 응답"만 한다.
  선택 목록·한도 → repeatcut/rules.py       환경변수 설정 → repeatcut/settings.py
  SQL            → repeatcut/repository.py  DB 구조 변경 → repeatcut/database.py
  이미지 저장    → repeatcut/image_storage.py     로그인 계산   → repeatcut/auth.py

로그인: /api/auth/* 로 토큰을 받고, 나머지 API는 `Authorization: Bearer <토큰>` 헤더가 있어야 한다.
        (로그인 없이 되는 것: /api/health, /api/options, /api/auth/register, /api/auth/login)
        각 API 함수의 `user: dict = Depends(current_user)` 가 그 확인을 한다.
"""
import logging
import os
import sqlite3
import sys
import uuid
from datetime import datetime
from typing import Optional

# `uvicorn main:app`(backend 폴더 안에서)과 `uvicorn backend.main:app`(루트에서) 둘 다 되도록 경로를 맞춘다.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from repeatcut import advice, auth, database, repository as repo
from repeatcut.bootstrap import init_db as _init_db
from repeatcut.image_storage import ImageError, build_image_storage, decode_image_data
from repeatcut.rules import (
    ANSWER_CHOICES, DEFAULT_EXAM, EXAM_TYPES, FIRST_YEAR, MAX_ANSWER_LENGTH, MAX_EMAIL_LENGTH, MAX_EXAM_LENGTH,
    MAX_KEYWORD_LENGTH, MAX_NICKNAME_LENGTH, MAX_PASSWORD_LENGTH, MAX_QUESTIONS, MAX_TITLE_LENGTH,
    MIN_PASSWORD_LENGTH, REASON_TYPES, ROUNDS, clean, year_choices,
)
from repeatcut.settings import load_settings

log = logging.getLogger("repeatcut")

settings = load_settings()
storage = build_image_storage(settings)


def get_db():
    """요청 하나가 쓰는 DB 연결. `with get_db() as conn:` 으로 쓰면 끝날 때 저장하고 닫는다."""
    return database.session(settings.db_path)


def raw_connection():
    """저장·닫기를 직접 해야 하는 연결 (테스트나 점검용)."""
    return database.connect(settings.db_path)


def init_db():
    return _init_db(settings, storage)


# ──────────────────────────────────────────────
# 요청 데이터 모양
# ──────────────────────────────────────────────
class RegisterInput(BaseModel):
    email: str
    password: str
    nickname: str = ""  # 화면에 보여줄 이름 (선택)


class LoginInput(BaseModel):
    email: str
    password: str


class AttemptInput(BaseModel):
    is_correct: bool  # 다시 풀어서 맞혔으면 true, 또 틀렸으면 false
    my_answer: str = ""  # 또 틀렸을 때 이번에 고른 답 (선택)
    reason_type: str = ""  # 또 틀렸을 때 이번에 틀린 이유 (선택 목록)


class PaperInput(BaseModel):
    exam: str = DEFAULT_EXAM
    year: int
    exam_type: str = "기출"
    round: str = "기타"
    title: str = ""  # 비우면 자동 이름
    total_questions: Optional[int] = None  # 문항 수 (선택)


class MistakeInput(BaseModel):
    paper_id: int
    problem_no: str
    page: int = 0  # 0 = 입력 안 함 (선택). 같은 문제를 가르는 기준은 문제지 + 문제 번호라서 페이지는 비워도 된다
    keyword: str
    reason_type: str
    memo: str = ""
    my_answer: str = ""  # 내가 고른 답 (선택)
    correct_answer: str = ""  # 정답 (선택)
    image_data: str


class MistakeUpdate(BaseModel):
    paper_id: int
    problem_no: str
    page: int = 0  # 0 = 입력 안 함
    keyword: str
    reason_type: str
    memo: str = ""
    my_answer: str = ""
    correct_answer: str = ""
    image_data: Optional[str] = None  # 있으면 문제 이미지를 이 이미지로 바꾼다. 없으면 그대로 둔다


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
init_db()


# ──────────────────────────────────────────────
# 로그인 확인
#   API 함수에 `user: dict = Depends(current_user)` 를 적으면, FastAPI가 그 함수를 실행하기 전에
#   current_user를 먼저 실행한다. 토큰이 없거나 틀리면 여기서 401로 끝나고 API 함수는 실행되지 않는다.
# ──────────────────────────────────────────────
# FastAPI가 제공하는 "Authorization: Bearer <토큰>" 헤더 읽기 도구.
#  - 이걸 쓰면 /docs(Swagger) 화면에 "Authorize" 버튼이 생겨서, 토큰을 한 번 넣고 모든 API를 눌러 볼 수 있다.
#  - auto_error=False: 헤더가 없을 때 FastAPI가 알아서 에러를 내지 않고 None을 준다. (에러 문장은 아래에서 직접 정한다)
bearer_scheme = HTTPBearer(auto_error=False)


def bearer_token(credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme)):
    """요청의 Authorization 헤더에서 토큰만 꺼낸다. 없으면 빈 문자열."""
    return credentials.credentials if credentials else ""


def current_user(token: str = Depends(bearer_token)):
    """로그인한 회원 {id, email, nickname}. 로그인 상태가 아니면 401."""
    if not token:
        raise HTTPException(status_code=401, detail="로그인이 필요해요.", headers={"WWW-Authenticate": "Bearer"})
    with get_db() as conn:
        user = repo.find_session_user(conn, auth.hash_token(token))
    if not user:
        raise HTTPException(
            status_code=401, detail="로그인이 만료됐어요. 다시 로그인해 주세요.", headers={"WWW-Authenticate": "Bearer"}
        )
    return user


def start_session(conn, user_id):
    """로그인 상태를 하나 만들고 토큰을 돌려준다. DB에는 토큰의 해시만 저장한다."""
    token = auth.new_token()
    repo.create_session(conn, user_id, auth.hash_token(token), auth.session_expiry())
    return token


# ──────────────────────────────────────────────
# 입력 검사 (문제가 있으면 400/404, 괜찮으면 정리된 값을 돌려준다)
# ──────────────────────────────────────────────
def check_paper_fields(item):
    exam = clean(item.exam) or DEFAULT_EXAM
    title = clean(item.title)
    if not (FIRST_YEAR <= item.year <= datetime.now().year + 1):
        raise HTTPException(status_code=400, detail="연도를 목록에서 선택해 주세요.")
    if item.exam_type not in EXAM_TYPES:
        raise HTTPException(status_code=400, detail="시험 구분을 목록에서 선택해 주세요.")
    if item.round not in ROUNDS:
        raise HTTPException(status_code=400, detail="회차를 목록에서 선택해 주세요.")
    if len(exam) > MAX_EXAM_LENGTH or len(title) > MAX_TITLE_LENGTH:
        raise HTTPException(status_code=400, detail=f"시험명은 {MAX_EXAM_LENGTH}자, 문제지 이름은 {MAX_TITLE_LENGTH}자 이하로 입력해 주세요.")
    if item.total_questions is not None and not (1 <= item.total_questions <= MAX_QUESTIONS):
        raise HTTPException(status_code=400, detail=f"문항 수는 1~{MAX_QUESTIONS} 사이로 입력해 주세요.")
    return {"exam": exam, "title": title, "total_questions": item.total_questions}


def check_mistake_fields(conn, user_id, item, current=None):
    """current: 수정할 때의 지금 오답(dict). 새로 등록할 때는 None."""
    problem_no = clean(item.problem_no)
    keyword = clean(item.keyword)
    memo = item.memo.strip()
    my_answer = clean(item.my_answer)
    correct_answer = clean(item.correct_answer)
    if not problem_no or not keyword:
        raise HTTPException(status_code=400, detail="문제 번호와 핵심 키워드를 확인해 주세요.")
    if item.page < 0:
        raise HTTPException(status_code=400, detail="페이지는 1 이상으로 입력하거나 비워 두세요.")
    if len(keyword) > MAX_KEYWORD_LENGTH:
        raise HTTPException(status_code=400, detail=f"핵심 키워드는 {MAX_KEYWORD_LENGTH}자 이하로 입력해 주세요.")
    if item.reason_type not in REASON_TYPES:
        raise HTTPException(status_code=400, detail="오답 이유를 목록에서 선택해 주세요.")
    if len(my_answer) > MAX_ANSWER_LENGTH or len(correct_answer) > MAX_ANSWER_LENGTH:
        raise HTTPException(status_code=400, detail=f"답은 {MAX_ANSWER_LENGTH}자 이하로 입력해 주세요.")
    if my_answer and correct_answer and my_answer.casefold() == correct_answer.casefold():
        raise HTTPException(status_code=400, detail="내가 고른 답과 정답이 같아요.")
    if not repo.paper_exists(conn, user_id, item.paper_id):  # 남의 문제지 id를 넣어도 여기서 걸린다
        raise HTTPException(status_code=404, detail="선택한 문제지를 찾을 수 없어요.")
    # 같은 문제지의 같은 번호는 한 번만 등록한다. 또 틀린 것은 '다시 푼 기록'(attempts)에 쌓는다.
    # (수정할 때는 문제지나 번호를 바꾼 경우에만 확인한다. 예전에 이미 중복으로 들어간 기록도 메모 등은 고칠 수 있게)
    moved = current is None or current["paper_id"] != item.paper_id or current["problem_no"].casefold() != problem_no.casefold()
    if moved and repo.find_same_problem(conn, user_id, item.paper_id, problem_no):
        raise HTTPException(status_code=409, detail="이 문제지에 같은 번호의 문제가 이미 등록돼 있어요. 그 문제에 '또 틀림'으로 기록해 주세요.")
    return {"problem_no": problem_no, "keyword": keyword, "memo": memo, "my_answer": my_answer, "correct_answer": correct_answer}


# ──────────────────────────────────────────────
# 기본
# ──────────────────────────────────────────────
@app.get("/api/health")
def health():
    """배포 서버의 상태 확인용. DB에 실제로 접속해 본다."""
    with get_db() as conn:
        conn.execute("SELECT 1").fetchone()
        schema_version = database.get_version(conn)
    return {"ok": True, "schema_version": schema_version, "storage": storage.name}


# ──────────────────────────────────────────────
# 회원가입 / 로그인
# ──────────────────────────────────────────────
@app.post("/api/auth/register", status_code=201)
def register(item: RegisterInput):
    email = item.email.strip().lower()
    nickname = clean(item.nickname)
    if len(email) > MAX_EMAIL_LENGTH or not auth.is_valid_email(email):
        raise HTTPException(status_code=400, detail="이메일 형식을 확인해 주세요.")
    if not (MIN_PASSWORD_LENGTH <= len(item.password) <= MAX_PASSWORD_LENGTH):
        raise HTTPException(status_code=400, detail=f"비밀번호는 {MIN_PASSWORD_LENGTH}자 이상 {MAX_PASSWORD_LENGTH}자 이하로 입력해 주세요.")
    if len(nickname) > MAX_NICKNAME_LENGTH:
        raise HTTPException(status_code=400, detail=f"이름은 {MAX_NICKNAME_LENGTH}자 이하로 입력해 주세요.")

    password_hash = auth.hash_password(item.password)  # 계산이 오래 걸리므로 DB 연결을 열기 전에 해 둔다
    with get_db() as conn:
        if repo.find_user_by_email(conn, email):
            raise HTTPException(status_code=409, detail="이미 가입된 이메일이에요.")
        try:
            user_id = repo.create_user(conn, email, password_hash, nickname)
        except sqlite3.IntegrityError:  # 같은 이메일로 동시에 가입 요청이 온 경우
            raise HTTPException(status_code=409, detail="이미 가입된 이메일이에요.")
        # 첫 번째 회원은 로그인 기능이 생기기 전에 만든 기록(예시 데이터 포함)을 넘겨받는다
        claimed_papers = repo.claim_unowned_papers(conn, user_id) if repo.count_users(conn) == 1 else 0
        token = start_session(conn, user_id)
        user = repo.get_user(conn, user_id)
    return {"token": token, "user": user, "claimed_papers": claimed_papers}


@app.post("/api/auth/login")
def login(item: LoginInput):
    email = item.email.strip().lower()
    # 이메일이 없는 경우와 비밀번호가 틀린 경우를 같은 문장으로 답한다. (가입된 이메일인지 알려주지 않기 위해)
    wrong = HTTPException(status_code=401, detail="이메일 또는 비밀번호가 맞지 않아요.")
    if len(item.password) > MAX_PASSWORD_LENGTH:
        raise wrong
    with get_db() as conn:
        row = repo.find_user_by_email(conn, email)
    if not row or not auth.verify_password(item.password, row["password_hash"]):
        raise wrong
    with get_db() as conn:
        repo.delete_expired_sessions(conn)  # 기한이 지난 로그인 상태는 이때 정리한다
        token = start_session(conn, row["id"])
    return {"token": token, "user": repo.public_user(row)}


@app.post("/api/auth/logout")
def logout(token: str = Depends(bearer_token)):
    """이 토큰의 로그인 상태를 지운다. 이후 같은 토큰으로는 요청할 수 없다."""
    if token:
        with get_db() as conn:
            repo.delete_session(conn, auth.hash_token(token))
    return {"ok": True}


@app.get("/api/auth/me")
def me(user: dict = Depends(current_user)):
    """지금 토큰이 누구 것인지. (프론트가 새로고침 뒤에 로그인 상태를 확인할 때 쓴다)"""
    return user


# ── 선택 목록 ──
@app.get("/api/options")
def get_options():
    return {
        "exam_default": DEFAULT_EXAM,
        "exam_types": EXAM_TYPES,
        "rounds": ROUNDS,
        "reason_types": REASON_TYPES,
        "answer_choices": ANSWER_CHOICES,
        "years": year_choices(),
        "max_questions": MAX_QUESTIONS,
    }


@app.get("/api/keywords")
def list_keywords(user: dict = Depends(current_user)):
    """자동완성용 키워드 목록. 많이 쓴 키워드가 위로 온다."""
    with get_db() as conn:
        return repo.list_keywords(conn, user["id"])


@app.get("/api/exams")
def list_exams(user: dict = Depends(current_user)):
    """자동완성용 시험명 목록. 내가 문제지에 써 본 시험명만 나온다."""
    with get_db() as conn:
        return repo.list_exams(conn, user["id"])


class ExamRename(BaseModel):
    name: str


@app.put("/api/exams/{exam_id}")
def rename_exam(exam_id: int, item: ExamRename, user: dict = Depends(current_user)):
    """내 문제지에 붙은 시험명을 바꾼다. (대소문자 고치기 포함)
    다른 회원의 문제지에는 영향을 주지 않는다."""
    name = clean(item.name)
    if not name:
        raise HTTPException(status_code=400, detail="시험 이름을 입력해 주세요.")
    if len(name) > MAX_EXAM_LENGTH:
        raise HTTPException(status_code=400, detail=f"시험 이름은 {MAX_EXAM_LENGTH}자 이하로 입력해 주세요.")
    with get_db() as conn:
        if not repo.user_has_exam(conn, user["id"], exam_id):
            raise HTTPException(status_code=404, detail="시험을 찾을 수 없어요.")
        try:
            new_id = repo.rename_exam(conn, user["id"], exam_id, name)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        return {"id": new_id, "name": name}


@app.delete("/api/exams/{exam_id}")
def delete_exam(exam_id: int, with_mistakes: bool = False, user: dict = Depends(current_user)):
    """내 문제지 중 이 시험에 속한 것을 지운다.
    오답이 걸려 있으면 with_mistakes=true 를 같이 보내야 오답(과 이미지)까지 지운다."""
    with get_db() as conn:
        if not repo.user_has_exam(conn, user["id"], exam_id):
            raise HTTPException(status_code=404, detail="시험을 찾을 수 없어요.")
        counts = repo.count_exam_contents(conn, user["id"], exam_id)
        if counts["mistakes"] and not with_mistakes:
            raise HTTPException(
                status_code=409,
                detail=f"이 시험에 문제지 {counts['papers']}개, 오답 {counts['mistakes']}개가 있어요. 오답까지 지우려면 한 번 더 확인해 주세요.",
            )
        filenames = repo.delete_exam_for_user(conn, user["id"], exam_id)
        leftover = {name for name in filenames if repo.count_image_references(conn, name) > 0}
    for filename in filenames:
        if filename in leftover:
            continue
        try:
            storage.delete(filename)
        except Exception:
            log.exception("이미지 파일을 지우지 못했어요(DB에서는 삭제됨): %s", filename)
    return {"ok": True, **counts}


# ──────────────────────────────────────────────
# 문제지정보
# ──────────────────────────────────────────────
@app.get("/api/papers")
def list_papers(user: dict = Depends(current_user)):
    """가장 최근에 쓴 문제지가 맨 위. (프론트는 맨 위 문제지를 기본 선택한다)"""
    with get_db() as conn:
        return repo.list_papers(conn, user["id"])


@app.post("/api/papers", status_code=201)
def create_paper(item: PaperInput, response: Response, user: dict = Depends(current_user)):
    fields = check_paper_fields(item)
    with get_db() as conn:
        paper_id, created = repo.get_or_create_paper(
            conn, user["id"], fields["exam"], item.year, item.exam_type, item.round, fields["title"],
            total_questions=fields["total_questions"],
        )
        if not created and fields["total_questions"] is not None:
            # 이미 있던 문제지인데 문항 수가 비어 있었다면, 이번에 입력한 값으로 채워준다
            repo.fill_total_questions_if_empty(conn, paper_id, fields["total_questions"])
        paper = repo.get_paper(conn, user["id"], paper_id)
    if not created:
        response.status_code = 200  # 이미 있던 문제지면 새로 만들지 않고 그걸 돌려준다
    return paper


@app.put("/api/papers/{paper_id}")
def update_paper(paper_id: int, item: PaperInput, user: dict = Depends(current_user)):
    fields = check_paper_fields(item)
    with get_db() as conn:
        if not repo.paper_exists(conn, user["id"], paper_id):
            raise HTTPException(status_code=404, detail="문제지를 찾을 수 없어요.")
        exam_id = repo.get_or_create_exam(conn, fields["exam"])
        # 바꾼 값이 내 다른 문제지와 똑같아지면 안 된다 (UNIQUE 충돌)
        same_id = repo.find_paper_id(conn, user["id"], exam_id, item.year, item.exam_type, item.round, fields["title"])
        if same_id and same_id != paper_id:
            raise HTTPException(status_code=409, detail="이미 있는 문제지예요.")
        # 이미 등록된 오답 수보다 문항 수를 적게 만들 수는 없다
        count = repo.count_mistakes_in_paper(conn, paper_id)
        if fields["total_questions"] is not None and fields["total_questions"] < count:
            raise HTTPException(status_code=400, detail=f"이 문제지에 이미 등록된 오답이 {count}개라서 문항 수를 그보다 적게 할 수 없어요.")
        repo.update_paper(
            conn, user["id"], paper_id, exam_id, item.year, item.exam_type, item.round, fields["title"], fields["total_questions"]
        )
        repo.delete_unused_exams(conn)  # 시험명을 바꿨다면 예전 시험명이 안 쓰일 수 있다
        return repo.get_paper(conn, user["id"], paper_id)


@app.delete("/api/papers/{paper_id}")
def delete_paper(paper_id: int, user: dict = Depends(current_user)):
    with get_db() as conn:
        if not repo.paper_exists(conn, user["id"], paper_id):
            raise HTTPException(status_code=404, detail="문제지를 찾을 수 없어요.")
        count = repo.count_mistakes_in_paper(conn, paper_id)
        if count:
            raise HTTPException(status_code=409, detail=f"이 문제지에 오답 {count}개가 연결되어 있어서 삭제할 수 없어요.")
        repo.delete_paper(conn, user["id"], paper_id)
        repo.delete_unused_exams(conn)
    return {"ok": True}


# ──────────────────────────────────────────────
# 통계
# ──────────────────────────────────────────────
@app.get("/api/stats")
def get_stats(paper_id: Optional[int] = None, user: dict = Depends(current_user)):
    """내 오답만 집계한다. paper_id를 주면 그중 그 문제지의 오답만 집계한다."""
    with get_db() as conn:
        if paper_id and not repo.paper_exists(conn, user["id"], paper_id):
            raise HTTPException(status_code=404, detail="문제지를 찾을 수 없어요.")
        return repo.get_stats(conn, user["id"], paper_id)


# 학습 추천: 같은 통계로 이미 받은 AI 추천을 다시 쓰기 위한 메모리 캐시 (서버를 끄면 비워진다)
advice_cache = {}
# Gemini를 부르는 함수. 테스트에서는 이 변수를 가짜 함수로 바꿔서 실제 호출 없이 확인한다.
gemini_caller = advice.call_gemini


@app.post("/api/stats/advice")
def get_study_advice(paper_id: Optional[int] = None, user: dict = Depends(current_user)):
    """내 통계를 바탕으로 학습 추천을 만든다. (버튼을 눌렀을 때만 호출되도록 POST로 두었다)
    Gemini API 키가 없거나 호출이 실패하면 규칙으로 만든 추천을 돌려주므로, 이 API 자체는 실패하지 않는다."""
    with get_db() as conn:
        if paper_id and not repo.paper_exists(conn, user["id"], paper_id):
            raise HTTPException(status_code=404, detail="문제지를 찾을 수 없어요.")
        stats = repo.get_stats(conn, user["id"], paper_id)
    # DB 연결을 닫은 뒤에 AI를 부른다. (응답을 기다리는 동안 DB를 붙잡고 있지 않게)
    result = advice.make_advice(
        stats, settings.gemini_api_key, settings.gemini_model, settings.gemini_timeout_seconds,
        advice_cache, caller=gemini_caller,
    )
    if result.get("error_kind"):
        # error_detail에는 Google의 에러 설명이나 연결 실패 이유가 들어 있다. (API 키는 헤더로만 보내서 여기에 없다)
        log.warning("Gemini 호출 실패(%s): %s → 규칙 기반 추천으로 대신함", result["error_kind"], result.get("error_detail", ""))
    return result


# ──────────────────────────────────────────────
# 오답노트
# ──────────────────────────────────────────────
@app.get("/api/mistakes")
def list_mistakes(keyword: Optional[str] = None, order: str = "newest", paper_id: Optional[int] = None,
                  user: dict = Depends(current_user)):
    """paper_id를 주면 그 문제지의 오답만. 남의 문제지 번호를 줘도 회원 조건 때문에 빈 목록이 나온다."""
    with get_db() as conn:
        return repo.list_mistakes(conn, user["id"], keyword, order, paper_id)


@app.get("/api/mistakes/lookup")
def lookup_mistake(paper_id: int, problem_no: str, user: dict = Depends(current_user)):
    """등록 화면용: 이 문제지의 이 문제 번호를 이미 등록했는지. 있으면 그 오답을, 없으면 null을 돌려준다."""
    with get_db() as conn:
        mistake_id = repo.find_same_problem(conn, user["id"], paper_id, problem_no)
        return {"mistake": repo.get_mistake(conn, user["id"], mistake_id) if mistake_id else None}


@app.get("/api/mistakes/trend")
def mistake_trend(user: dict = Depends(current_user)):
    with get_db() as conn:
        return repo.mistake_trend(conn, user["id"])


@app.get("/api/mistakes/{mistake_id}/image")
def get_mistake_image(mistake_id: int, user: dict = Depends(current_user)):
    """내 오답의 이미지만 내려준다. (<img src>는 헤더를 못 보내서, 프론트는 fetch로 받아 보여준다 → src/components/AuthImage.jsx)"""
    with get_db() as conn:
        filename = repo.get_mistake_image_path(conn, user["id"], mistake_id)
    if not filename:
        raise HTTPException(status_code=404, detail="이미지를 찾을 수 없어요.")
    try:
        served = storage.serve(filename)
    except Exception:
        log.exception("이미지 저장소에서 읽지 못했어요: %s", filename)
        raise HTTPException(status_code=502, detail="이미지 저장소에 연결하지 못했어요.")
    if served is None:
        raise HTTPException(status_code=404, detail="이미지 파일을 찾을 수 없어요.")
    if served.kind == "redirect":
        return RedirectResponse(served.location, status_code=302)
    # 파일 이름은 한 번 만들면 내용이 바뀌지 않아서 브라우저가 하루 동안 다시 받지 않아도 된다
    return FileResponse(served.location, headers={"Cache-Control": "private, max-age=86400"})


@app.post("/api/mistakes", status_code=201)
def create_mistake(item: MistakeInput, user: dict = Depends(current_user)):
    with get_db() as conn:
        fields = check_mistake_fields(conn, user["id"], item)
        try:
            image_bytes, extension, content_type = decode_image_data(item.image_data, settings.max_image_bytes)
        except ImageError as error:
            raise HTTPException(status_code=error.status, detail=error.message)

        image_no = f"IMG-{uuid.uuid4().hex[:12].upper()}"
        filename = f"{image_no.lower()}.{extension}"
        # 이미지를 먼저 저장하고 DB에 기록한다. DB 기록이 실패하면 방금 저장한 이미지를 지운다.
        try:
            storage.save(filename, image_bytes, content_type)
        except Exception:
            log.exception("이미지를 저장하지 못했어요: %s", filename)
            raise HTTPException(status_code=500, detail="이미지를 저장하지 못했어요.")
        try:
            keyword_id = repo.get_or_create_keyword(conn, fields["keyword"])
            mistake_id = repo.insert_mistake(
                conn, paper_id=item.paper_id, problem_no=fields["problem_no"], page=item.page, keyword_id=keyword_id,
                reason_type=item.reason_type, memo=fields["memo"], my_answer=fields["my_answer"],
                correct_answer=fields["correct_answer"], image_no=image_no, image_path=filename,
            )
            conn.commit()  # 저장이 끝난 뒤에 응답용으로 다시 읽는다
        except Exception:
            log.exception("오답을 저장하지 못했어요")
            conn.rollback()
            try:
                storage.delete(filename)
            except Exception:
                log.exception("실패한 요청의 이미지를 지우지 못했어요: %s", filename)
            raise HTTPException(status_code=500, detail="오답을 저장하지 못했어요.")
        return repo.get_mistake(conn, user["id"], mistake_id)


@app.put("/api/mistakes/{mistake_id}")
def update_mistake(mistake_id: int, item: MistakeUpdate, user: dict = Depends(current_user)):
    new_image = None  # (파일 이름, 바이트, content_type) — 이미지를 바꿀 때만
    if item.image_data:
        try:
            image_bytes, extension, content_type = decode_image_data(item.image_data, settings.max_image_bytes)
        except ImageError as exc:
            raise HTTPException(status_code=exc.status, detail=exc.message)
        new_image = (f"img-{uuid.uuid4().hex[:12]}.{extension}", image_bytes, content_type)

    old_filename = None
    with get_db() as conn:
        current = repo.get_mistake(conn, user["id"], mistake_id)
        if not current:
            raise HTTPException(status_code=404, detail="항목을 찾을 수 없어요.")
        fields = check_mistake_fields(conn, user["id"], item, current)
        keyword_id = repo.get_or_create_keyword(conn, fields["keyword"])
        if new_image:
            old_filename = repo.get_mistake_image_path(conn, user["id"], mistake_id)
            try:
                storage.save(*new_image)  # 새 파일을 먼저 저장한다. 실패하면 DB는 그대로
            except Exception:
                log.exception("이미지를 저장하지 못했어요")
                raise HTTPException(status_code=500, detail="이미지를 저장하지 못했어요.")
        repo.update_mistake(
            conn, mistake_id, paper_id=item.paper_id, problem_no=fields["problem_no"], page=item.page,
            keyword_id=keyword_id, reason_type=item.reason_type, memo=fields["memo"],
            my_answer=fields["my_answer"], correct_answer=fields["correct_answer"],
        )
        if new_image:
            repo.update_mistake_image(conn, mistake_id, new_image[0])
        repo.delete_unused_keywords(conn)  # 키워드를 바꿨다면 예전 키워드가 안 쓰일 수 있다
        old_still_used = bool(old_filename) and repo.count_image_references(conn, old_filename) > 0
        result = repo.get_mistake(conn, user["id"], mistake_id)
    # DB를 바꾼 뒤에 예전 이미지를 지운다. 지우기에 실패해도 수정은 이미 끝났으니 성공으로 본다.
    if old_filename and not old_still_used:
        try:
            storage.delete(old_filename)
        except Exception:
            log.exception("예전 이미지 파일을 지우지 못했어요: %s", old_filename)
    return result


@app.delete("/api/mistakes/{mistake_id}")
def delete_mistake(mistake_id: int, user: dict = Depends(current_user)):
    with get_db() as conn:
        filename = repo.get_mistake_image_path(conn, user["id"], mistake_id)
        if not filename:
            raise HTTPException(status_code=404, detail="항목을 찾을 수 없어요.")
        repo.delete_mistake(conn, mistake_id)
        repo.delete_unused_keywords(conn)
        still_used = repo.count_image_references(conn, filename) > 0  # 다른 오답이 같은 파일을 쓰면 남겨둔다
    # DB 기록을 먼저 지우고 이미지를 지운다. 이미지 삭제가 실패해도 오답은 이미 지워졌으니 요청은 성공으로 본다.
    if not still_used:
        try:
            storage.delete(filename)
        except Exception:
            log.exception("이미지 파일을 지우지 못했어요(DB에서는 삭제됨): %s", filename)
    return {"ok": True}


# ──────────────────────────────────────────────
# 다시 푼 기록 (오답을 다시 풀어 본 결과: 맞음 / 또 틀림)
# ──────────────────────────────────────────────
@app.get("/api/mistakes/{mistake_id}/attempts")
def list_attempts(mistake_id: int, user: dict = Depends(current_user)):
    with get_db() as conn:
        if not repo.mistake_exists(conn, user["id"], mistake_id):
            raise HTTPException(status_code=404, detail="항목을 찾을 수 없어요.")
        return repo.list_attempts(conn, mistake_id)


@app.post("/api/mistakes/{mistake_id}/attempts", status_code=201)
def create_attempt(mistake_id: int, item: AttemptInput, user: dict = Depends(current_user)):
    """기록을 하나 더하고, 요약(다시 푼 횟수 등)이 바뀐 오답과 기록 목록을 함께 돌려준다."""
    with get_db() as conn:
        mistake = repo.get_mistake(conn, user["id"], mistake_id)
        if not mistake:
            raise HTTPException(status_code=404, detail="항목을 찾을 수 없어요.")
        # 맞혔으면 고른 답과 틀린 이유는 기록하지 않는다
        my_answer = "" if item.is_correct else clean(item.my_answer)
        reason_type = "" if item.is_correct else item.reason_type
        if reason_type and reason_type not in REASON_TYPES:
            raise HTTPException(status_code=400, detail="오답 이유를 목록에서 선택해 주세요.")
        if len(my_answer) > MAX_ANSWER_LENGTH:
            raise HTTPException(status_code=400, detail=f"답은 {MAX_ANSWER_LENGTH}자 이하로 입력해 주세요.")
        if my_answer and mistake["correct_answer"] and my_answer.casefold() == mistake["correct_answer"].casefold():
            raise HTTPException(status_code=400, detail="고른 답이 정답과 같아요. 맞혔다면 '맞혔어요'로 기록해 주세요.")
        repo.insert_attempt(conn, mistake_id, item.is_correct, my_answer, reason_type)
        return {"mistake": repo.get_mistake(conn, user["id"], mistake_id), "attempts": repo.list_attempts(conn, mistake_id)}


@app.delete("/api/mistakes/{mistake_id}/attempts/{attempt_id}")
def delete_attempt(mistake_id: int, attempt_id: int, user: dict = Depends(current_user)):
    """잘못 누른 기록을 지운다."""
    with get_db() as conn:
        if not repo.mistake_exists(conn, user["id"], mistake_id):
            raise HTTPException(status_code=404, detail="항목을 찾을 수 없어요.")
        if repo.delete_attempt(conn, mistake_id, attempt_id) == 0:
            raise HTTPException(status_code=404, detail="다시 푼 기록을 찾을 수 없어요.")
        return {"mistake": repo.get_mistake(conn, user["id"], mistake_id), "attempts": repo.list_attempts(conn, mistake_id)}
