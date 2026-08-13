"""
物流 RAG 引擎 — 本地 Embedding + FAISS 检索 + LLM 问答
"""
from __future__ import annotations

import json
import os
import pickle
import re
import time
from pathlib import Path
from typing import Dict, List, Tuple

import faiss
import numpy as np
import requests
from sentence_transformers import SentenceTransformer

from config import LLM_API_URL, LLM_API_KEY, LLM_MODEL, LLM_TIMEOUT
from rag_config import (
    DOCUMENTS_DIR,
    VECTOR_STORE_DIR,
    EMBEDDING_MODEL,
    CHUNK_SIZE,
    CHUNK_OVERLAP,
    TOP_K,
)
from rag_data_loader import load_documents


def _split_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    text = re.sub(r"\r\n", "\n", text).strip()
    if len(text) <= size:
        return [text] if text else []
    chunks: List[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            cut = max(text.rfind("\n", start, end), text.rfind("。", start, end), text.rfind("，", start, end), text.rfind(" ", start, end))
            if cut > start + size // 2:
                end = cut + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


class RagEngine:
    def __init__(self):
        self.documents_dir = DOCUMENTS_DIR
        self.vector_store_dir = VECTOR_STORE_DIR
        self.embedding_model = EMBEDDING_MODEL
        self.api_key = LLM_API_KEY
        self.llm_url = LLM_API_URL
        self.llm_model = LLM_MODEL
        self.model = None
        self.index = None
        self.chunks: List[Dict] = []
        self.status = {
            "loaded_docs": 0,
            "chunk_count": 0,
            "reused_vector_db": False,
            "error": "",
        }

    def _ensure_model(self):
        if self.model is None:
            self.model = SentenceTransformer(self.embedding_model)

    def _embed_texts(self, texts: List[str]) -> np.ndarray:
        self._ensure_model()
        vectors = self.model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
            batch_size=32,
        )
        return np.asarray(vectors, dtype="float32")

    def initialize(self, rebuild: bool = False):
        index_file = self.vector_store_dir / "index.faiss"
        chunks_file = self.vector_store_dir / "chunks.pkl"
        if not rebuild and index_file.exists() and chunks_file.exists():
            try:
                self._ensure_model()
                self.index = faiss.read_index(str(index_file))
                with open(chunks_file, "rb") as f:
                    self.chunks = pickle.load(f)
                self.status.update({
                    "loaded_docs": 0,
                    "chunk_count": len(self.chunks),
                    "reused_vector_db": True,
                    "error": "",
                })
                print(f"[RAG] 已加载向量库：{len(self.chunks)} 个分块")
                return self.status
            except Exception as e:
                print(f"[RAG] 向量库加载失败，准备重建: {e}")

        docs = load_documents()
        chunks: List[Dict] = []
        for doc in docs:
            for text in _split_text(doc.get("text") or ""):
                chunks.append({"text": text, "metadata": doc.get("metadata") or {}})
        if not chunks:
            self.status.update({"error": "没有可索引的物流数据"})
            return self.status

        self._ensure_model()
        vectors = self._embed_texts([c["text"] for c in chunks])
        index = faiss.IndexFlatIP(vectors.shape[1])
        index.add(vectors)
        self.index = index
        self.chunks = chunks
        self.vector_store_dir.mkdir(parents=True, exist_ok=True)
        faiss.write_index(index, str(self.vector_store_dir / "index.faiss"))
        with open(self.vector_store_dir / "chunks.pkl", "wb") as f:
            pickle.dump(chunks, f)
        self.status.update({
            "loaded_docs": len(docs),
            "chunk_count": len(chunks),
            "reused_vector_db": False,
            "error": "",
        })
        print(f"[RAG] 向量库构建完成：{len(docs)} 条文档，{len(chunks)} 个分块")
        return self.status

    def retrieve(self, question: str, k: int = TOP_K) -> List[Dict]:
        if self.index is None or not self.chunks:
            raise RuntimeError("RAG 尚未初始化")
        vector = self._embed_texts([question])
        scores, indices = self.index.search(vector, min(k, len(self.chunks)))
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue
            results.append({
                "text": self.chunks[idx]["text"],
                "metadata": self.chunks[idx]["metadata"],
                "score": round(float(score), 4),
            })
        return results

    def ask(self, question: str, top_k: int = TOP_K) -> Tuple[str, List[Dict]]:
        docs = self.retrieve(question, top_k)
        if not docs:
            return "资料库中没有找到相关信息。", []
        context = "\n\n".join(
            f"[来源:{d['metadata'].get('source', '未知')}]\n{d['text']}" for d in docs
        )
        prompt = (
            "你是物流运输路径优化专家。请仅依据以下物流资料回答。\n"
            "优先使用资料中的数字、字段名和事实；如果资料中不存在答案，"
            "请明确说“资料中未找到相关信息”，禁止编造。\n\n"
            f"问题：{question}\n\n资料：\n{context}"
        )
        answer = self._call_llm(prompt)
        sources = []
        seen = set()
        for d in docs:
            source = str(d["metadata"].get("source", "未知"))
            if source in seen:
                continue
            seen.add(source)
            sources.append({
                "source": source,
                "score": d["score"],
            })
        return answer, sources

    def _call_llm(self, prompt: str) -> str:
        if not self.api_key:
            return "未配置 LLM API Key，无法生成回答。"
        payload = {
            "model": self.llm_model,
            "messages": [
                {"role": "system", "content": "你是物流运输路径优化专家，擅长基于资料严谨回答。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "stream": False,
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            resp = requests.post(self.llm_url, json=payload, headers=headers, timeout=LLM_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            return f"LLM 调用失败：{e}"
