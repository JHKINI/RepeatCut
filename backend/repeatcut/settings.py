"""배포 환경마다 달라지는 값은 전부 환경변수로 받는다. (코드를 고치지 않고 서버 설정만 바꿔서 배포할 수 있게)

| 환경변수                       | 기본값                              | 설명                                              |
|-------------------------------|-------------------------------------|---------------------------------------------------|
| REPEATCUT_DB                  | /workspace/data/app.db              | SQLite 파일 경로 (영속 디스크에 두기)               |
| REPEATCUT_UPLOAD_DIR          | (DB 파일 옆) uploads/               | 이미지를 저장할 폴더 (storage=local 일 때)          |
| REPEATCUT_STORAGE             | local                               | 이미지 저장소: local 또는 s3                        |
| REPEATCUT_S3_BUCKET           | (s3일 때 필수)                       | 버킷 이름                                          |
| REPEATCUT_S3_PREFIX           | problem-images/                     | 버킷 안의 폴더(키 앞부분)                           |
| REPEATCUT_S3_ENDPOINT         | (없음)                              | S3 호환 저장소 주소 (Cloudflare R2, MinIO 등)       |
| REPEATCUT_S3_REGION           | (없음)                              | 리전                                               |
| REPEATCUT_S3_PUBLIC_BASE_URL  | (없음)                              | 버킷이 공개(CDN 등)라면 그 주소. 없으면 임시 URL 사용 |
| REPEATCUT_S3_PRESIGN_SECONDS  | 3600                                | 임시 URL 유효 시간(초)                              |
| REPEATCUT_CORS_ORIGINS        | localhost:5173,5174 (127.0.0.1 포함) | 프론트 주소 목록 (쉼표로 구분)                       |
| REPEATCUT_MAX_IMAGE_MB        | 5                                   | 업로드 이미지 최대 크기(MB)                         |
| REPEATCUT_BACKUP              | 1                                   | 1이면 DB 구조를 바꾸기 전에 자동 백업               |
| REPEATCUT_GEMINI_API_KEY      | (없음)                              | Gemini API 키. 없으면 학습 추천을 규칙으로 만든다     |
| REPEATCUT_GEMINI_MODEL        | gemini-3.8-flash                    | 학습 추천에 쓸 Gemini 모델 이름                      |
| REPEATCUT_GEMINI_TIMEOUT      | 20                                  | Gemini 응답을 기다리는 최대 시간(초)                 |

S3 접근 키는 boto3 표준 환경변수(AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)를 그대로 쓴다.
"""
import os
from dataclasses import dataclass
from pathlib import Path

# 이 파일은 backend/repeatcut/ 안에 있으므로, 프로젝트 루트는 세 단계 위다.
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB_PATH = "/workspace/data/app.db"
DEFAULT_CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
]
# 예전 버전이 이미지를 저장하던 폴더. 새 이미지는 여기에 저장하지 않지만,
# 이미 저장된 이미지를 계속 보여주기 위해 읽기 전용으로 함께 찾아본다.
LEGACY_UPLOAD_DIR = str(PROJECT_ROOT / "public" / "problem-images")


@dataclass(frozen=True)
class Settings:
    db_path: str
    upload_dir: str
    legacy_upload_dirs: tuple
    storage_backend: str  # "local" 또는 "s3"
    s3_bucket: str
    s3_prefix: str
    s3_endpoint_url: str
    s3_region: str
    s3_public_base_url: str
    s3_presign_seconds: int
    cors_origins: tuple
    max_image_bytes: int
    backup_before_migrate: bool
    gemini_api_key: str  # 비밀 값. 로그나 응답에 넣지 않는다
    gemini_model: str
    gemini_timeout_seconds: float


def _flag(value, default):
    if value is None or value == "":
        return default
    return value.strip().lower() not in ("0", "false", "no", "off")


def _number(env, name, default, cast=int):
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return cast(raw)
    except ValueError:
        raise ValueError(f"환경변수 {name} 값이 숫자가 아니에요: {raw!r}")


def load_settings(env=None):
    """환경변수를 읽어 Settings를 만든다. (env를 넘기면 그 값으로, 안 넘기면 os.environ으로)"""
    env = os.environ if env is None else env

    db_path = env.get("REPEATCUT_DB") or DEFAULT_DB_PATH
    # 이미지 폴더 기본값은 DB 파일 바로 옆. 디스크 하나만 마운트·백업하면 DB와 이미지가 같이 따라간다.
    upload_dir = env.get("REPEATCUT_UPLOAD_DIR") or os.path.join(os.path.dirname(db_path), "uploads")

    storage_backend = (env.get("REPEATCUT_STORAGE") or "local").strip().lower()
    if storage_backend not in ("local", "s3"):
        raise ValueError(f"REPEATCUT_STORAGE는 local 또는 s3여야 해요: {storage_backend!r}")
    s3_bucket = (env.get("REPEATCUT_S3_BUCKET") or "").strip()
    if storage_backend == "s3" and not s3_bucket:
        raise ValueError("REPEATCUT_STORAGE=s3 이면 REPEATCUT_S3_BUCKET도 설정해야 해요.")

    prefix = (env.get("REPEATCUT_S3_PREFIX") if env.get("REPEATCUT_S3_PREFIX") is not None else "problem-images/").strip().lstrip("/")
    if prefix and not prefix.endswith("/"):
        prefix += "/"

    origins_raw = env.get("REPEATCUT_CORS_ORIGINS")
    if origins_raw is None or origins_raw.strip() == "":
        cors_origins = tuple(DEFAULT_CORS_ORIGINS)
    else:
        cors_origins = tuple(origin.strip().rstrip("/") for origin in origins_raw.split(",") if origin.strip())

    return Settings(
        db_path=db_path,
        upload_dir=upload_dir,
        legacy_upload_dirs=(LEGACY_UPLOAD_DIR,),
        storage_backend=storage_backend,
        s3_bucket=s3_bucket,
        s3_prefix=prefix,
        s3_endpoint_url=(env.get("REPEATCUT_S3_ENDPOINT") or "").strip(),
        s3_region=(env.get("REPEATCUT_S3_REGION") or "").strip(),
        s3_public_base_url=(env.get("REPEATCUT_S3_PUBLIC_BASE_URL") or "").strip().rstrip("/"),
        s3_presign_seconds=_number(env, "REPEATCUT_S3_PRESIGN_SECONDS", 3600),
        cors_origins=cors_origins,
        max_image_bytes=int(_number(env, "REPEATCUT_MAX_IMAGE_MB", 5, float) * 1024 * 1024),
        backup_before_migrate=_flag(env.get("REPEATCUT_BACKUP"), True),
        # Google 문서의 기본 이름(GEMINI_API_KEY)으로 설정해 둔 경우도 받아 준다
        gemini_api_key=(env.get("REPEATCUT_GEMINI_API_KEY") or env.get("GEMINI_API_KEY") or "").strip(),
        # 모델 목록 API는 "models/이름" 형태로 주므로, 그대로 붙여 넣어도 되게 앞의 "models/"를 뗀다
        gemini_model=(env.get("REPEATCUT_GEMINI_MODEL") or "gemini-3.8-flash").strip().removeprefix("models/"),
        gemini_timeout_seconds=_number(env, "REPEATCUT_GEMINI_TIMEOUT", 20, float),
    )
