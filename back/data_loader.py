"""
数据加载器 — 加载并预处理基础数据表
基础数据源：工厂分配区间规则.xlsx
辅助数据：海运费参考标准.xlsx、港杂费标准、工厂到起运港拖车费等（由 app.py 独立加载）
"""
import pandas as pd
import numpy as np
from config import FILES, USD_TO_CNY


def _read_first_sheet(fpath):
    """读取Excel文件的第一个有效数据sheet（跳过Query sheet）"""
    try:
        all_sheets = pd.read_excel(fpath, sheet_name=None)
        for name, df in all_sheets.items():
            if df.shape[0] > 0 and df.shape[1] > 1:
                return df
    except Exception as e:
        print(f"[数据加载] 读取 {fpath} 失败: {e}")
    return pd.DataFrame()


def _try_parse_date_columns(df, columns):
    """尝试解析日期列，忽略不存在的列"""
    for col in columns:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors='coerce')


class DataLoader:
    """加载并缓存所有数据表（单例模式）"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._loaded = False
        return cls._instance

    def load_all(self):
        """加载所有数据表"""
        if self._loaded:
            return
        print("[数据加载] 正在加载工厂分配区间规则...")
        self.allocation_rules = self._load_allocation_rules()
        self.allocation_port_detail = self._load_allocation_port_detail()

        print(f"[数据加载] 完成")
        self._loaded = True

    # ===== 数据加载方法 =====
    def _load_allocation_rules(self):
        try:
            df = pd.read_excel(FILES["allocation_rules"], sheet_name="工厂分配规则")
        except Exception:
            df = _read_first_sheet(FILES["allocation_rules"])
        print(f"  工厂分配规则: {len(df)} 行, 列: {list(df.columns)}")
        return df

    def _load_allocation_port_detail(self):
        try:
            df = pd.read_excel(FILES["allocation_rules"], sheet_name="港口发货明细")
        except Exception:
            df = pd.DataFrame()
        print(f"  港口发货明细: {len(df)} 行, 列: {list(df.columns)}")
        return df
