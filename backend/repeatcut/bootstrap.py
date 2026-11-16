"""서버가 켜질 때 DB를 준비한다."""
import logging

from . import database
from .database import table_exists
from .seed import insert_seed_data

log = logging.getLogger("repeatcut")


def init_db(settings, storage):
    """구조 변경 적용 → (새 DB면) 예시 데이터. 여러 번 실행해도 안전하다."""
    conn = database.connect(settings.db_path)
    try:
        is_new_db = not table_exists(conn, "mistakes")  # 예전 DB든 새 DB든 mistakes가 있으면 새 DB가 아님
    finally:
        conn.close()

    applied, backup_path = database.migrate(settings.db_path, backup=settings.backup_before_migrate)
    if backup_path:
        log.info("DB 구조를 바꾸기 전에 백업했어요: %s", backup_path)
    if applied:
        log.info("DB 구조 변경 적용: %s", applied)
    database.enable_wal(settings.db_path)

    with database.session(settings.db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")  # 서버가 동시에 켜져도 예시 데이터가 두 번 들어가지 않게 잠금을 잡는다
        if is_new_db and conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 0:
            insert_seed_data(conn, storage)
    return applied, backup_path
