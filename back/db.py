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

    primary = result.get("data", {}).get("primary", {}) if isinstance(result, dict) else {}
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
        return True
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
    """保存推荐结果，失败只记录日志不影响接口"""
    if not DB_ENABLED:
        return
    try:
        save_recommendation(input_data, result)
        print(f"[MySQL] 推荐结果已保存: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    except Exception as e:
        print(f"[MySQL] 保存推荐结果失败: {e}")
