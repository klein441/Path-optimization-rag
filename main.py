"""
物流运输路径智能优化系统 — 启动入口
"""
import sys
import os

# 添加 back 目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'back'))

from app import app, get_engine
import config


def main():
    print("=" * 60)
    print("  物流运输路径智能优化系统")
    print("  Logistics Route Optimization API")
    print("=" * 60)
    print(f"  LLM 模式: {'启用 (' + config.LLM_MODEL + ')' if config.LLM_ENABLED else '未启用（使用规则引擎）'}")
    print(f"  监听地址: http://{config.HOST}:{config.PORT}")
    print(f"  数据源: {len(config.FILES)} 张 Excel 表")
    print("=" * 60)

    # 预加载数据并构建知识库
    print("\n[预加载] 正在加载数据并构建知识库...")
    get_engine()
    print("[预加载] 完成\n")

    # 启动服务
    app.run(host=config.HOST, port=config.PORT, debug=True)


if __name__ == '__main__':
    main()
