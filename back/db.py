"""
MySQL 持久化模块 — 保存推荐输入的原始请求和推荐输出结果
未配置或连接失败时静默降级，不影响推荐接口正常返回
"""
import json
import time
import hashlib
import os

import pymysql
import pymysql.cursors

from config import (
    USD_TO_CNY,
    DB_ENABLED,
    DB_HOST,
    DB_PORT,
    DB_USER,
    DB_PASSWORD,
    DB_NAME,
    DB_CHARSET,
)


def _connect():
    """创建 MySQL 连接"""
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset=DB_CHARSET,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )


def _hash_password(password):
    """生成带随机盐的密码哈希"""
    salt = os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), bytes.fromhex(salt), 100000).hex()
    return f"{salt}${digest}"


def _verify_password(password, stored):
    """校验密码是否匹配存储的哈希"""
    try:
        salt, digest = stored.split('$', 1)
        calc = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), bytes.fromhex(salt), 100000).hex()
        return calc == digest
    except (ValueError, TypeError):
        return False


def init_db():
    """初始化结果记录表（幂等）"""
    if not DB_ENABLED:
        return False
    conn = _connect()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS logistics_recommendation_log (
                    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    input_data LONGTEXT NULL,
                    output_data LONGTEXT NULL,
                    primary_factory VARCHAR(255) NULL,
                    primary_origin_port VARCHAR(255) NULL,
                    primary_dest_port VARCHAR(255) NULL,
                    trade_term VARCHAR(32) NULL,
                    total_cost DECIMAL(18,2) NULL,
                    total_days INT NULL,
                    score DECIMAL(5,1) NULL,
                    PRIMARY KEY (id),
                    KEY idx_created_at (created_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS logistics_users (
                    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                    username VARCHAR(64) NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (id),
                    UNIQUE KEY uk_username (username)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS recommendation_feedback (
                    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    log_id BIGINT UNSIGNED NULL,
                    user_action VARCHAR(32) NOT NULL,
                    chosen_factory VARCHAR(255) NULL,
                    chosen_port VARCHAR(255) NULL,
                    delta_cost DECIMAL(18,2) NULL,
                    note VARCHAR(512) NULL,
                    PRIMARY KEY (id),
                    KEY idx_log_id (log_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            cursor.execute("SELECT id FROM logistics_users WHERE username = %s", ("admin",))
            if not cursor.fetchone():
                cursor.execute(
                    "INSERT INTO logistics_users (username, password_hash) VALUES (%s, %s)",
                    ("admin", _hash_password("admin123")),
                )
        return True
    finally:
        conn.close()


def register_user(username, password):
    """注册用户并写入 MySQL，返回 {"ok": bool, "error": str}"""
    if not DB_ENABLED:
        return {"ok": False, "error": "数据库未启用，无法注册"}
    conn = _connect()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM logistics_users WHERE username = %s", (username,))
            if cursor.fetchone():
                return {"ok": False, "error": "用户名已存在"}
            cursor.execute(
                "INSERT INTO logistics_users (username, password_hash) VALUES (%s, %s)",
                (username, _hash_password(password)),
            )
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": f"注册失败: {e}"}
    finally:
        conn.close()


def verify_user(username, password):
    """校验用户名和密码，返回 True/False"""
    if not DB_ENABLED:
        return False
    conn = _connect()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT password_hash FROM logistics_users WHERE username = %s",
                (username,),
            )
            row = cursor.fetchone()
            if not row:
                return False
            return _verify_password(password, row.get("password_hash") or "")
    except Exception:
        return False
    finally:
        conn.close()


def save_recommendation(input_data, result):
    """保存一次推荐请求的输入与输出结果"""
    if not DB_ENABLED:
        return False

    payload = result.get("data", {}) if isinstance(result, dict) and isinstance(result.get("data"), dict) else result
    primary = payload.get("primary", {}) if isinstance(payload, dict) else {}
    cost = primary.get("cost", {})
    timeline = primary.get("timeline", {})
    score = primary.get("score")

    conn = _connect()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO logistics_recommendation_log (
                    input_data, output_data, primary_factory, primary_origin_port,
                    primary_dest_port, trade_term, total_cost, total_days, score
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    json.dumps(input_data, ensure_ascii=False),
                    json.dumps(result, ensure_ascii=False),
                    primary.get("factoryShort") or primary.get("factory") or "",
                    primary.get("departurePort") or "",
                    primary.get("destPort") or "",
                    primary.get("tradeTerm") or "",
                    cost.get("totalCny") if cost else None,
                    timeline.get("total_days") if timeline else None,
                    score,
                ),
            )
            new_id = cursor.lastrowid
        return new_id
    finally:
        conn.close()


def update_recommendation_total(input_data, total_cny, fee_items=None):
    """Update the latest log row for the original request with the frontend-confirmed total."""
    if not DB_ENABLED or total_cny is None:
        return False

    input_json = json.dumps(input_data, ensure_ascii=False)
    total = round(float(total_cny), 2)
    conn = _connect()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, output_data
                FROM logistics_recommendation_log
                WHERE input_data = %s
                ORDER BY id DESC
                LIMIT 1
                """,
                (input_json,),
            )
            row = cursor.fetchone()
            if not row:
                return False

            output_data = row.get("output_data")
            parsed = None
            if isinstance(output_data, str):
                try:
                    parsed = json.loads(output_data)
                except (TypeError, ValueError):
                    parsed = None
            elif isinstance(output_data, dict):
                parsed = output_data

            new_output_data = None
            if parsed and isinstance(parsed, dict):
                primary = parsed.get("data", {}).get("primary", {})
                cost = primary.get("cost") if isinstance(primary, dict) else None
                if isinstance(cost, dict):
                    cost["totalCny"] = total
                    cost["totalUsd"] = round(total / USD_TO_CNY, 2)
                    cost["confirmed_by_user"] = True
                    if fee_items is not None:
                        cost["items"] = fee_items
                    new_output_data = json.dumps(parsed, ensure_ascii=False)

            cursor.execute(
                """
                UPDATE logistics_recommendation_log
                SET total_cost = %s, output_data = COALESCE(%s, output_data)
                WHERE id = %s
                """,
                (total, new_output_data, row["id"]),
            )
        return True
    finally:
        conn.close()


def safe_update_recommendation_total(input_data, total_cny, fee_items=None):
    """Update the confirmed fee total without breaking the confirmation flow."""
    if not DB_ENABLED:
        return False
    try:
        return update_recommendation_total(input_data, total_cny, fee_items)
    except Exception as e:
        print(f"[MySQL] 更新费用确认总额失败: {e}")
        return False


def safe_init_db():
    """启动时安全初始化，失败不阻断服务"""
    if not DB_ENABLED:
        return
    try:
        init_db()
        print("[MySQL] 初始化完成")
    except Exception as e:
        print(f"[MySQL] 初始化失败，已跳过: {e}")


def safe_save_recommendation(input_data, result):
    """保存推荐结果，失败只记录日志不影响接口；成功返回 log_id"""
    if not DB_ENABLED:
        return None
    try:
        log_id = save_recommendation(input_data, result)
        print(f"[MySQL] 推荐结果已保存: log_id={log_id} {time.strftime('%Y-%m-%d %H:%M:%S')}")
        return log_id
    except Exception as e:
        print(f"[MySQL] 保存推荐结果失败: {e}")
        return None


def save_feedback(log_id, user_action, chosen_factory=None, chosen_port=None, delta_cost=None, note=None):
    """保存用户反馈（确认/改选/费用修正），用于自适应学习"""
    if not DB_ENABLED:
        return False
    if user_action not in ("confirm", "modify", "switch_alternative"):
        user_action = "note"
    conn = _connect()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO recommendation_feedback (
                    log_id, user_action, chosen_factory, chosen_port, delta_cost, note
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (log_id, user_action, chosen_factory, chosen_port,
                 round(float(delta_cost), 2) if delta_cost is not None else None, note),
            )
        return True
    finally:
        conn.close()


def safe_save_feedback(log_id, user_action, chosen_factory=None, chosen_port=None, delta_cost=None, note=None):
    """保存反馈，失败不阻断主流程"""
    if not DB_ENABLED:
        return False
    try:
        ok = save_feedback(log_id, user_action, chosen_factory, chosen_port, delta_cost, note)
        print(f"[MySQL] 反馈已保存: action={user_action} log_id={log_id}")
        return ok
    except Exception as e:
        print(f"[MySQL] 保存反馈失败: {e}")
        return False


def fetch_feedback_rows(limit=5000):
    """读取反馈并关联推荐日志（用于反馈调权），失败返回空列表"""
    if not DB_ENABLED:
        return []
    try:
        conn = _connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT f.id, f.log_id, f.user_action, f.chosen_factory, f.chosen_port,
                           f.delta_cost, f.note,
                           l.primary_factory, l.primary_origin_port
                    FROM recommendation_feedback f
                    LEFT JOIN logistics_recommendation_log l ON f.log_id = l.id
                    ORDER BY f.id ASC
                    LIMIT %s
                    """,
                    (limit,),
                )
                return cursor.fetchall()
        finally:
            conn.close()
    except Exception as e:
        print(f"[MySQL] 读取反馈失败: {e}")
        return []


def get_feedback_max_id():
    """反馈表最大 id（用于缓存增量判断）"""
    if not DB_ENABLED:
        return 0
    try:
        conn = _connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT COALESCE(MAX(id), 0) AS m FROM recommendation_feedback")
                row = cursor.fetchone()
                return int(row["m"] or 0)
        finally:
            conn.close()
    except Exception:
        return 0
