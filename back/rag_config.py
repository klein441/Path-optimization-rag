"""
RAG 模块配置 — 物流知识问答的数据目录与向量库路径
"""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOCUMENTS_DIR = PROJECT_ROOT / "data"
VECTOR_STORE_DIR = PROJECT_ROOT / "data" / "vector_store_faiss"

EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"
CHUNK_SIZE = 700
CHUNK_OVERLAP = 120
TOP_K = 6
