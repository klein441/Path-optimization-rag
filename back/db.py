"""
MySQL 持久化模块 — 保存推荐输入的原始请求和推荐输出结果
未配置或连接失败时静默降级，不影响推荐接口正常返回
"""
import json
import time

import pymysql
import pymysql.cursors

from config import (
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
        return True
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
