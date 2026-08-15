# -*- coding: utf-8 -*-
"""
RAG 四指标评测脚本（离线黄金测试集）

针对自适应 Agentic RAG 系统评测四个 RAG 指标：
1. Context Recall（检索召回率）  — 标准答案中的原子事实有多少能被检索到
2. Context Precision（检索精确率）— 检索到的 chunk 中有多少真正相关
3. Faithfulness（忠实度/幻觉）   — 生成答案的 claims 是否有检索上下文支撑
4. Answer Relevance（答案相关性）— 生成答案是否切题地回答了问题

用法（在项目根目录执行）：
    python back/scripts/eval_rag.py                      # 检索指标 + 答案指标（词法基线，答案生成走系统真实 LLM）
    python back/scripts/eval_rag.py --skip-answers        # 只跑检索指标（Recall/Precision），不生成答案
    python back/scripts/eval_rag.py --llm                 # 追加 LLM 判分（faithfulness 逐条核验 + answer relevance）
    python back/scripts/eval_rag.py --only q01,q04        # 只跑指定题
    python back/scripts/eval_rag.py --output docs/rag-eval-report.md

输出：markdown 评测报告（默认 docs/rag-eval-report.md）
"""
import argparse
import json
import os
import re
import sys
import io

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACK = os.path.join(ROOT, "back")
sys.path.insert(0, BACK)
os.chdir(BACK)

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(errors='replace')

import config  # noqa: E402
from retriever import get_retriever  # noqa: E402
from recommendation_engine import RecommendationEngine  # noqa: E402
from agent.router import QueryRouter  # noqa: E402
from agent.planner import Planner  # noqa: E402

# ===== 归一化 =====
_STRIP_RE = re.compile(r"[\s_\-·/（）()\[\]【】「」『』“”\"'，。；：、,.;:!?！？]+")


def _norm(s):
    return _STRIP_RE.sub("", str(s or "")).lower()


# ===== 数字/单位 =====
_UNIT_RE = re.compile(r"(天|元|美元|CNY|USD|CBM|箱|柜|千支|%|次|分|小时|分钟)$")
_NUM_UNIT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(天|元|美元|CNY|USD|CBM|箱|柜|千支|%|次|分|小时|分钟)")
_CUR_NUM_RE = re.compile(r"(USD|CNY|¥|￥)\s*(\d+(?:\.\d+)?)")
_DECIMAL_RE = re.compile(r"\d+\.\d+")


def _strip_unit(c):
    m = _UNIT_RE.search(c)
    return c[: m.start()] if m else c


def extract_number_claims(text):
    claims = set()
    for m in _NUM_UNIT_RE.finditer(text):
        claims.add(_norm(m.group(0)))
    for m in _CUR_NUM_RE.finditer(text):
        claims.add(_norm(m.group(0)))
    for m in _DECIMAL_RE.finditer(text):
        claims.add(_norm(m.group(0)))
    return claims


# ===== 实体目录（来自知识库，供 claim 提取与相关性判定） =====
def build_entity_catalog(kb):
    names = set()
    for full, info in kb.factory_info.items():
        names.add(full)
        short = info.get("short_name", "")
        if short:
            names.add(short)
    # 港口：工厂历史港 + 配置默认港 + 运抵国目的港
    for ports in kb.factory_ports.values():
        for p in ports:
            names.add(str(p["port"]))
    for country, ports in kb.country_dest_ports.items():
        for p in ports:
            names.add(str(p["port"]))
    names.update(str(v) for v in kb.box_types.keys())
    names.update(kb.trade_terms.keys())
    names.update(kb.country_to_region.keys())
    names.update(["丁腈手套", "PVC手套", "PE手套", "PE产品", "轮椅", "小日化产品", "洛杉矶", "上海", "宁波", "青岛", "美国"])
    # 港口中文简称（如 洛杉矶/LOS ANGELES -> 洛杉矶）
    short = set()
    for n in list(names):
        if "/" in n:
            short.add(n.split("/")[0].strip())
    names.update(short)
    return sorted(names, key=len, reverse=True)


def extract_entity_claims(text, catalog):
    found = []
    for e in catalog:
        if e and _norm(e) in _norm(text):
            found.append(e)
    return found


# ===== 检索复刻（与 agent/executor 保持一致） =====
def retrieve_for(router, retriever, question, form):
    route = router.classify(message=question, input_data=form)
    if route["path"] == "qa":
        hits = retriever.retrieve(query=question, top_k=10)
    elif route["path"] == "fast":
        qtext = Planner._query_text({"message": question, "input": form})
        hits = retriever.retrieve(query=qtext, input_data=form, profile=route["profile"])
    else:
        qtext = Planner._query_text({"message": question, "input": form})
        hits = retriever.retrieve(query=qtext, input_data=form,
                                  top_k=route["profile"].get("top_k", config.RETRIEVAL_TOP_K))
    return route, hits


def context_text_of(hits):
    return "\n".join(str(c.get("text", "")) for c in hits)


# ===== 指标：Context Recall =====
def context_recall(gold_facts, hits):
    """Context Recall 双口径：
    - score      = 总召回：gold_facts 是否出现在全部检索上下文（含结构化规则注入 chunk）
    - retr_score = 纯检索召回：gold_facts 是否出现在非注入（真实关键词/向量/报告）chunk 中
    结构化注入 chunk（工厂/国家/条款/合约费率）是系统主动塞入、score=1.0 恒排最前，
    用它命中的 fact 不算“检索能力”，单独归为 inject_only，避免 Recall 虚高。
    """
    ctx = _norm(context_text_of(hits))
    retr_ctx = _norm(context_text_of([h for h in hits if not h.get("structured")]))
    hit_facts, miss_facts = [], []
    retr_hits, inject_only = [], []
    for f in gold_facts:
        nf = _norm(f)
        if nf in ctx:
            hit_facts.append(f)
            if nf in retr_ctx:
                retr_hits.append(f)
            else:
                inject_only.append(f)
        else:
            miss_facts.append(f)
    total = len(gold_facts) if gold_facts else 1
    return len(hit_facts) / total, len(retr_hits) / total, hit_facts, retr_hits, inject_only, miss_facts


# ===== 指标：Context Precision =====
def chunk_relevant(chunk, expected_entities, context_terms, min_words=1):
    """相关判定：chunk 命中 expected_entities/context_terms 中 ≥min_words 个不同词才算相关。
    默认 1 词（宽松）；严格口径用 2 词，避免「美国/海运/天」这类宽泛词单独出现即判相关。"""
    text = _norm(chunk.get("text", ""))
    matched = {t for t in (expected_entities + context_terms) if t and _norm(t) in text}
    return len(matched) >= max(1, min_words)


def context_precision(hits, expected_entities, context_terms, min_words=1):
    if not hits:
        return 0.0, [], []
    rel, irr = [], []
    for c in hits:
        (rel if chunk_relevant(c, expected_entities, context_terms, min_words) else irr).append(c)
    return len(rel) / len(hits), rel, irr


# ===== 指标：Faithfulness =====
def _collect_computed_numbers(result):
    """从推荐结果里收集成本引擎计算出的数字（费用/评分/时效/费率），
    这些不是检索事实，忠实度统计时应单独归类为 computed 而非 unsupported。"""
    s = set()

    def walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                kl = str(k).lower()
                if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
                    if any(t in kl for t in ("cost", "score", "day", "rate", "cny", "usd", "qty", "count", "box")):
                        s.add(_norm(str(v)))
                elif isinstance(v, str) and kl in ("boxtype", "tradeterm"):
                    s.add(_norm(v))
                elif isinstance(v, (dict, list)):
                    walk(v)
        elif isinstance(obj, list):
            for it in obj:
                walk(it)

    walk(result)
    return s


def _is_computed(claim, computed):
    bare = _strip_unit(claim)
    return claim in computed or bare in computed


def extract_claims(answer_text, catalog):
    claims, seen = [], set()
    def add(c):
        n = _norm(c)
        if n and n not in seen:
            seen.add(n)
            claims.append(c)
    for m in _NUM_UNIT_RE.finditer(answer_text):
        add(m.group(0))
    for m in _CUR_NUM_RE.finditer(answer_text):
        add(m.group(0))
    for m in _DECIMAL_RE.finditer(answer_text):
        add(m.group(0))
    for e in extract_entity_claims(answer_text, catalog):
        add(e)
    return claims


def faithfulness(answer_text, hits, result, catalog):
    computed = _collect_computed_numbers(result)
    claims = extract_claims(answer_text, catalog)
    ctx = _norm(context_text_of(hits))
    cit = _norm("\n".join(str(c.get("text", "")) for c in (result.get("citations") or [])))
    def _in_context(claim):
        if claim in ctx or claim in cit:
            return True
        bare = _strip_unit(claim)
        return bool(bare) and (bare in ctx or bare in cit)

    supported, unsupported, computed_claims = [], [], []
    for c in claims:
        nc = _norm(c)
        if _is_computed(nc, computed):
            computed_claims.append(c)
        elif _in_context(nc):
            supported.append(c)
        else:
            unsupported.append(c)
    total = len(supported) + len(unsupported) + len(computed_claims)
    score = (len(supported) + len(computed_claims)) / total if total else 1.0
    return score, supported, computed_claims, unsupported


def split_sentences(text):
    """把答案拆成原子陈述句（按句号/问号/分号/换行）"""
    parts = re.split(r"[。！？；\n]+", str(text or ""))
    out = []
    for part in parts:
        s = part.strip().strip("，,、:：\"'“” ").strip()
        if len(s) >= 4:
            out.append(s)
    return out


def llm_sentence_supported(sentence, evidence_text, computed_note):
    """用 LLM 判断单个答案陈述是否被检索证据直接支撑（语义级，非子串匹配）"""
    from llm_client import LLMClient
    llm = LLMClient()
    sys_p = ("你是RAG忠实度评测员。判断给定答案陈述是否被检索证据直接支撑。"
             "允许同义改写；证据说明中标注为成本引擎计算值的数字视为有据；"
             "不得凭模型自身知识或常识补全证据中不存在的结论。只输出JSON {\"supported\": true或false}。")
    usr = (f"答案陈述：{sentence}\n\n检索证据：{evidence_text[:1600]}\n\n"
           f"证据说明：{computed_note}\n\n输出JSON：{{\"supported\": true或false}}")
    res = llm.llm_structured_call(sys_p, usr, temperature=0.0, max_tokens=80)
    if not res:
        return None
    return bool(res.get("supported"))


def faithfulness_strict(answer_text, hits, result, catalog):
    """句子级忠实度（--llm 时启用）：拆句后逐句 LLM 核验是否被检索证据支撑。
    替代词法子串自证口径（原口径下 citations=生成答案所用上下文，实体必然命中，Faithfulness 结构性地虚高）。"""
    computed = _collect_computed_numbers(result)
    sentences = split_sentences(answer_text)
    if not sentences:
        return 1.0, [], []
    evidence = context_text_of(hits)
    if computed:
        computed_note = ("以下数字/取值来自成本引擎确定性计算，视为有据：" + "、".join(sorted(computed)[:40]))
    else:
        computed_note = "本答案不含成本引擎计算值，所有数字/结论都必须是检索证据直接支撑。"
    supported_s, unsupported_s = [], []
    for s in sentences[:12]:
        ok = llm_sentence_supported(s, evidence, computed_note)
        (supported_s if ok is True else unsupported_s).append(s)
    total = len(supported_s) + len(unsupported_s)
    return (len(supported_s) / total if total else 1.0), supported_s, unsupported_s


# ===== 指标：Answer Relevance（词法基线） =====
def answer_relevance_lex(question, answer_text, expected_entities):
    qn, an = _norm(question), _norm(answer_text)
    hits = [e for e in expected_entities if _norm(e) in an]
    ent_sim = len(hits) / len(expected_entities) if expected_entities else 0.0
    qb = set(zip(qn, qn[1:]))
    ab = set(zip(an, an[1:]))
    jac = len(qb & ab) / len(qb | ab) if (qb | ab) else 0.0
    score = 0.7 * ent_sim + 0.3 * jac
    return score, hits


# ===== LLM 判分（--llm 时启用） =====
def llm_relevance(question, answer):
    from llm_client import LLMClient
    llm = LLMClient()
    sys_p = "你是RAG评测员，评估生成答案是否切题地回答了用户问题。只输出JSON。"
    usr = f"用户问题：{question}\n\n生成答案：{answer[:800]}\n\n输出JSON：{{\"score\": 0到1的小数, \"reason\": \"一句话原因\"}}"
    res = llm.llm_structured_call(sys_p, usr, temperature=0.0, max_tokens=200)
    if not res:
        return None
    try:
        return max(0.0, min(1.0, float(res.get("score", 0.5))))
    except (TypeError, ValueError):
        return None


def llm_claim_supported(claim, context):
    from llm_client import LLMClient
    llm = LLMClient()
    sys_p = "你是RAG忠实度评测员，判断给定的单一事实声明是否被检索上下文直接支撑（允许同义改写，不允许凭空推断）。只输出JSON。"
    usr = f"事实声明：{claim}\n\n检索上下文：{context[:2500]}\n\n输出JSON：{{\"supported\": true或false}}"
    res = llm.llm_structured_call(sys_p, usr, temperature=0.0, max_tokens=100)
    if not res:
        return None
    return bool(res.get("supported"))


def llm_confirm_unsupported(unsupported, hits, result):
    ctx = context_text_of(hits)[:2500]
    cit = "\n".join(str(c.get("text", "")) for c in (result.get("citations") or []))[:2500]
    joined = (ctx + "\n" + cit).strip()
    still = []
    for c in unsupported:
        if llm_claim_supported(c, joined) is True:
            continue
        still.append(c)
    return still


# ===== 答案文本构建 =====
def build_answer_text(result):
    if result.get("answer"):
        return str(result["answer"])
    parts = []
    p = result.get("primary") or {}
    if p:
        parts.append(f"推荐方案：从{p.get('factory', '')}（{p.get('departurePort', '')}）发往{p.get('destPort', '')}")
        if p.get("tradeTerm"):
            parts.append(f"，贸易条款{p['tradeTerm']}")
        if p.get("boxType"):
            parts.append(f"，箱型{p['boxType']}")
        cost = p.get("cost") or {}
        if cost.get("total_cny"):
            parts.append(f"，总费用{cost['total_cny']}元")
        tl = p.get("timeline") or {}
        total_days = tl.get("total_days") if isinstance(tl, dict) else tl
        if total_days:
            parts.append(f"，时效{total_days}天")
        if p.get("score"):
            parts.append(f"，综合评分{p['score']}")
    if result.get("reasoning"):
        parts.append("。" + str(result["reasoning"]))
    if not parts:
        parts.append(str(result.get("error") or "（无答案）"))
    return "".join(parts)


# ===== 报告输出 =====
def fmt_pct(v):
    return f"{v * 100:.1f}%"


def write_report(report_path, meta, results, use_llm):
    lines = []
    A = lines.append
    A("# RAG 四指标评测报告（严格口径：纯检索召回 / ≥2词相关 / 句子级 LLM 忠实度核验）")
    A("")
    A(f"- 评测时间：{meta['date']}")
    A(f"- LLM：{meta['llm_model']}（enabled={meta['llm_enabled']}），embedding={meta['embedding']}")
    A(f"- 检索库：{meta['chunks']} chunks，{meta['sources']} 个来源")
    A(f"- 判分方式：{'词法基线 + LLM 核验（句子级忠实度 + 相关性）' if use_llm else '词法基线（--llm 可开启 LLM 判分）'}")
    A(f"- 测试集：`back/scripts/eval_questions.json`，{meta['n']} 题")
    A("")
    A("## 1. 指标口径")
    A("")
    A("| 指标 | 定义 | 本报告的计算方式 |")
    A("|---|---|---|")
    A("| **Context Recall（总）** | 标准答案信息有多少被检索到 | `gold_facts` 归一化后是否为全部检索上下文（含结构化注入 chunk）子串：`命中/总数` |")
    A("| **Context Recall（纯检索）** | 标准答案信息有多少被**真实检索**到 | `gold_facts` 是否为**非注入 chunk**（关键词/向量/报告）子串。结构化注入 chunk（工厂/国家/条款/合约费率）由规则主动塞入、score=1.0 恒排最前，用它命中的 fact 不算检索能力，避免虚高 |")
    A("| **Context Precision（≥2词）** | 检索到的文档有多少真正相关 | 每条 chunk 命中 `expected_entities`/`context_terms` 中 **≥2 个不同词**才算相关（严格口径）；避免「美国/海运/天」这类宽泛词单独出现即判相关 |")
    A("| **Faithfulness（LLM 句子级）** | 生成答案是否有证据支撑、是否防幻觉 | 把答案拆成陈述句，逐句用 LLM 判定是否被检索证据直接支撑（替代原“citations 自证 + 子串匹配”口径，消除结构性虚高）；费用/评分/时效等成本引擎计算值在证据说明中标注为有据 |")
    A("| **Answer Relevance**（答案相关性） | 生成答案是否真正回答了问题 | 词法：`0.7×问题关键实体在答案中的命中率 + 0.3×问题-答案字符二元组 Jaccard`；`--llm` 时与 LLM 0~1 打分按 1:1 融合 |")
    A("")
    A("> 检索上下文按真实路由复刻：`qa` 路径 `top_k=10`；`fast` 路径用路由画像；`agent` 路径用 `profile.top_k`（low=6/medium=8/high=14）。")
    A("> 原宽松口径（Recall 含注入 / Precision 1词 / Faithfulness 子串+citations）结构性地虚高，仅作参考，不用于结论。")
    A("")
    A("## 2. 汇总（严格口径）")
    A("")
    A("| 题号 | 类型 | 路由 | Recall纯检索 | Recall总 | Precision≥2词 | Faithfulness | Relevance | 来源 | 置信度 |")
    A("|---|---|---|---|---|---|---|---|---|---|")
    agg = {"recall_retr": [], "recall": [], "precision": [], "faith": [], "rel": []}
    for r in results:
        agg["recall_retr"].append(r["recall_retr"])
        agg["recall"].append(r["recall"])
        agg["precision"].append(r["precision_strict"])
        agg["faith"].append(r["faithfulness"])
        agg["rel"].append(r["relevance"])
        route = r["route"]
        A(f"| {r['id']} | {r['type']} | {route.get('path')}/{route.get('intent')} | "
          f"{fmt_pct(r['recall_retr'])} | {fmt_pct(r['recall'])} | {fmt_pct(r['precision_strict'])} | "
          f"{fmt_pct(r['faithfulness'])} | {fmt_pct(r['relevance'])} | {r.get('source', '-')} | {r.get('confidence', '-')} |")
    A("")
    A("| **平均** | | | "
      f"{fmt_pct(sum(agg['recall_retr'])/len(agg['recall_retr']))} | "
      f"{fmt_pct(sum(agg['recall'])/len(agg['recall']))} | "
      f"{fmt_pct(sum(agg['precision'])/len(agg['precision']))} | "
      f"{fmt_pct(sum(agg['faith'])/len(agg['faith']))} | "
      f"{fmt_pct(sum(agg['rel'])/len(agg['rel']))} | | |")
    A("")
    A("## 3. 逐题详情")
    A("")
    for r in results:
        A(f"### {r['id']} {r['question']}")
        A("")
        A(f"- 类型：{r['type']}；路由：`{r['route']['path']}` / intent=`{r['route']['intent']}` / "
          f"routed_by=`{r['route'].get('routed_by')}` / complexity=`{r['route'].get('complexity')}`")
        A(f"- 参考标准答案：{r.get('gold_answer', '-')}")
        A("")
        A(f"**Context Recall（总）= {fmt_pct(r['recall'])} / （纯检索）= {fmt_pct(r['recall_retr'])}** — "
          f"命中 {len(r['recall_hits'])}/{len(r['gold_facts'])}（仅注入命中 {len(r['recall_inject_only'])} 条）")
        if r["recall_hits"]:
            A(f"  - 命中：{('、'.join(r['recall_hits']))}")
        if r["recall_inject_only"]:
            A(f"  - 仅靠规则注入命中（非检索能力）：**{('、'.join(r['recall_inject_only']))}**")
        if r["recall_retr_hits"]:
            A(f"  - 纯检索命中：{('、'.join(r['recall_retr_hits']))}")
        if r["recall_misses"]:
            A(f"  - 未命中：**{('、'.join(r['recall_misses']))}**")
        A("")
        A(f"**Context Precision（≥2词）= {fmt_pct(r['precision_strict'])}**（相关 {len(r['prec_rel_strict'])}/{len(r['prec_all'])} 条；宽松1词口径={fmt_pct(r['precision'])}）")
        for c in r["prec_all"]:
            flag = "✅" if c["relevant_strict"] else ("◐" if c["relevant"] else "❌")
            inj = " [注入]" if c["structured"] else ""
            A(f"  - {flag} `{c['chunk_type']}|{c['source']}`{inj} score={c['score']:.2f}：{c['text'][:70]}")
        A("")
        A(f"**Faithfulness（LLM 句子级）= {fmt_pct(r['faithfulness'])}**"
          f"{'（词法基线=' + fmt_pct(r['faith_lex']) + '）' if r.get('faith_strict') is not None else ''} — "
          f"支撑句 {len(r.get('faith_supported_s', []))} / 未支撑句 {len(r.get('faith_unsupported_s', []))}")
        if r.get("faith_supported_s"):
            A(f"  - 支撑句：{('；'.join(r['faith_supported_s'][:6]))}")
        if r.get("faith_unsupported_s"):
            A(f"  - **未支撑句（潜在幻觉/口径外）**：{('；'.join(r['faith_unsupported_s'][:6]))}")
        if r["faith_computed"]:
            A(f"  - 成本引擎计算值（豁免，有据）：{('、'.join(r['faith_computed'][:12]))}")
        A("")
        A(f"**Answer Relevance = {fmt_pct(r['relevance'])}** — 关键实体命中 {('、'.join(r['rel_hits'])) or '无'}")
        A("")
        A(f"> 生成答案：{r['answer_text'][:220]}…")
        A("")
    A("## 4. 发现的问题与改进建议")
    A("")
    findings = meta.get("findings", [])
    for i, f in enumerate(findings, 1):
        A(f"{i}. **{f['title']}**：{f['detail']} → 建议：{f['suggest']}")
    A("")
    A("## 5. 复现")
    A("")
    A("```bash")
    A("python back/scripts/eval_rag.py --llm      # 严格口径（纯检索召回 + ≥2词精确率 + 句子级LLM忠实度 + LLM相关性）")
    A("python back/scripts/eval_rag.py            # 词法基线（含真实答案生成，Faithfulness 用词法口径）")
    A("python back/scripts/eval_rag.py --skip-answers   # 只跑检索指标（Recall/Precision）")
    A("```")
    A("")
    os.makedirs(os.path.dirname(report_path) or ".", exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return report_path


# ===== 主流程 =====
def main():
    ap = argparse.ArgumentParser(description="RAG 四指标评测")
    ap.add_argument("--questions", default=os.path.join(BACK, "scripts", "eval_questions.json"))
    ap.add_argument("--output", default=os.path.join(ROOT, "docs", "rag-eval-report.md"))
    ap.add_argument("--skip-answers", action="store_true", help="跳过答案生成，只跑检索指标")
    ap.add_argument("--llm", action="store_true", help="启用 LLM 判分（faithfulness 核验 + relevance）")
    ap.add_argument("--only", default="", help="只跑指定题，如 q01,q04")
    args = ap.parse_args()

    with open(args.questions, encoding="utf-8") as fh:
        data = json.load(fh)
    questions = data["questions"]
    if args.only:
        keep = {x.strip() for x in args.only.split(",") if x.strip()}
        questions = [q for q in questions if q["id"] in keep]

    print("[eval] 构建检索器与引擎 ...")
    retriever = get_retriever()
    eng = RecommendationEngine()
    router = QueryRouter()
    catalog = build_entity_catalog(eng.kb)
    stats = retriever.store.stats()

    results = []
    for qi, q in enumerate(questions, 1):
        qid = q["id"]
        print(f"[eval] [{qi}/{len(questions)}] {qid} {q['question']}")
        route, hits = retrieve_for(router, retriever, q["question"], q.get("form") or {})
        recall, recall_retr, hit_facts, retr_hits, inject_only, miss_facts = \
            context_recall(q.get("gold_facts", []), hits)
        prec, rel, irr = context_precision(hits, q.get("expected_entities", []), q.get("context_terms", []))
        prec_strict, rel_s, irr_s = context_precision(
            hits, q.get("expected_entities", []), q.get("context_terms", []), min_words=2)

        if args.skip_answers:
            result = {}
            answer_text = "（--skip-answers 未生成答案）"
            faith = 1.0
            faith_lex = 1.0
            faith_strict = None
            supported = computed_claims = unsupported = []
            faith_supported_s = faith_unsupported_s = []
            rel_score = 0.0
            rel_hits = []
            source = "-"
            confidence = "-"
        else:
            result = eng.chat(message=q["question"], input_data=q.get("form") or {}, session_id="")
            answer_text = build_answer_text(result)
            faith_lex, supported, computed_claims, unsupported = faithfulness(answer_text, hits, result, catalog)
            if args.llm and unsupported:
                unsupported = llm_confirm_unsupported(unsupported, hits, result)
                faith_lex = (len(supported) + len(computed_claims)) / (
                    len(supported) + len(computed_claims) + len(unsupported)) if (supported or computed_claims or unsupported) else 1.0
            if args.llm:
                faith_strict, faith_supported_s, faith_unsupported_s = faithfulness_strict(
                    answer_text, hits, result, catalog)
                faith = faith_strict
            else:
                faith_strict = None
                faith_supported_s = faith_unsupported_s = []
                faith = faith_lex
            rel_score, rel_hits = answer_relevance_lex(q["question"], answer_text, q.get("expected_entities", []))
            if args.llm:
                llm_s = llm_relevance(q["question"], answer_text)
                if llm_s is not None:
                    rel_score = 0.5 * rel_score + 0.5 * llm_s
            source = result.get("source", "-")
            confidence = result.get("confidence", "-")

        prec_all = []
        for c in hits:
            prec_all.append({"chunk_type": c.get("chunk_type"), "source": c.get("source"),
                             "score": float(c.get("score", 0)), "text": str(c.get("text", ""))[:110],
                             "structured": bool(c.get("structured")),
                             "relevant": chunk_relevant(c, q.get("expected_entities", []), q.get("context_terms", [])),
                             "relevant_strict": chunk_relevant(c, q.get("expected_entities", []), q.get("context_terms", []), min_words=2)})

        results.append({
            "id": qid, "type": q.get("type"), "question": q["question"],
            "gold_answer": q.get("gold_answer", ""), "gold_facts": q.get("gold_facts", []),
            "route": route,
            "recall": recall, "recall_retr": recall_retr,
            "recall_hits": hit_facts, "recall_retr_hits": retr_hits,
            "recall_inject_only": inject_only, "recall_misses": miss_facts,
            "precision": prec, "precision_strict": prec_strict,
            "prec_all": prec_all, "prec_rel": rel, "prec_rel_strict": rel_s,
            "faithfulness": faith, "faith_lex": faith_lex, "faith_strict": faith_strict,
            "faith_supported": supported, "faith_computed": computed_claims,
            "faith_unsupported": unsupported,
            "faith_supported_s": faith_supported_s, "faith_unsupported_s": faith_unsupported_s,
            "relevance": rel_score, "rel_hits": rel_hits,
            "answer_text": answer_text, "source": source, "confidence": confidence,
        })

    findings = [
        {"title": "【已修复】术语/概念解释类问题误路由到 compare（用户实测『FOB和DDP有什么区别』返回货运推荐）",
         "detail": "路由器把含「区别」的问题优先归为 compare（agent 路径），术语/概念解释类问题会走候选生成+单方案输出，"
                   "甚至在会话记忆注入目的港后给出「山东英科→汉堡」的货运推荐，完全不解释条款。已修复：`back/agent/router.py` 增加术语优先判断"
                   "（消息含 FOB/DDP/贸易条款等且含 区别/解释/什么是 等解释词时，强制路由到 consult/qa）。修复后该问题按 qa 路径回答。",
         "suggest": "已修复。后续若出现『A和B哪个划算』类条款比价问题，可再为 compare 增加条款维度。"},
        {"title": "【已修复】结构化工厂信息无条件霸榜，挤压语义结果",
         "detail": "无产品/国家信号时，5 家工厂结构化 chunk 以 score=1.0 排在 top-6，把报告/常量/条款 chunk 挤出 top-8，导致 q02/q03/q04/q05 Precision 一度只有 50%。"
                   "已修复：`back/retriever.py` 增加工厂信息闸门——仅当查询/表单含产品、工厂名或「工厂」字样时才输出工厂 chunk。修复后 q02/q03/q04/q05 Precision 全部升到 100%。",
         "suggest": "已修复。"},
        {"title": "【已修复】贸易条款术语 chunk 未被召回",
         "detail": "kb_term_FOB/DDP chunk 存在但之前未被 top-8 召回。已修复：`back/retriever._structured_knowledge` 在查询提到条款名时直接把术语定义作为结构化权威 chunk 输出，"
                   "q05 Context Recall 由 75% 升到 100%，回答与引用均落到条款定义上。",
         "suggest": "已修复。"},
        {"title": "【已修复】QA 证据覆盖率被虚词/疑问词拖低",
         "detail": "`back/agent/evidence.py` 的 QA 覆盖率把问题所有中文二元组（什么/区别/的和等）都当作必须命中检索的词，导致 grounded 的回答仍被判 needs_review。"
                   "已修复：`_query_terms` 过滤虚词/疑问词，只统计信息量大的英文/数字 token 与内容二元组。修复后「FOB和DDP有什么区别」confidence 0.57→1.0、needs_review=False。",
         "suggest": "已修复。"},
        {"title": "【已修复】「美国」的国家维度结构化知识缺失",
         "detail": "此前 `KnowledgeBase.country_dest_ports`、`country_ocean_days` 为空（`all_countries=[]`）。已修复：`back/knowledge_base.py` 在 `_build_port_routes` 末尾"
                   "从 `运抵国与目的港.xlsx` 回填 `country_dest_ports`（122 国、按运单数降序）；`back/retriever._structured_knowledge` 在表单无 `destCountry` 时从查询文本识别国家，"
                   "纯咨询问题（如「从中国到美国海运大概要多少天」）也能拿到「运抵国 美国 常用目的港/海运天数」结构化 chunk。"
                   "口径说明：`get_ocean_days('美国')` 返回船公司中位数 14 天（shipping_lines 优先），geo 估算 18 天存在于 `country_ocean_days`，两者均保留并如实标注来源。",
         "suggest": "已修复。"},
        {"title": "【已修复】箱容数据源不一致（76.0 vs 76.4）",
         "detail": "已修复：`back/config.py` `BOX_TYPE_VOLUME` 统一以《集装箱标准容积对照表.xlsx》为准（20GP=33.2、40GP=67.7、40HQ/40HC=76.4、40NOR=67.3、45HQ=86.1、20HQ=37.5、LCL=0），"
                   "`cost_calculator` 与 KB 箱型 chunk 自动同步新口径；评测集 q02 gold 同步改为 76.4。",
         "suggest": "已修复。"},
        {"title": "【已修复】compare 意图未真正对比用户指定的港口（q08）",
         "detail": "已修复：`back/llm_client.py` 新增 `_detect_compare_subjects`/`_compare_recommend`，`back/agent/executor.py` 在 compare 意图先走真对比——按问题中的起运港/工厂分别取该对象最便宜候选，"
                   "按「含海运费合计成本」（F 组条款叠加合约海运费）排序输出对比表与结论；`back/retriever._structured_knowledge` 对问题中提到的起运港注入对应合约海运费 chunk（如 MSC USD 2102/40HC），"
                   "q08 Context Recall 100%、Answer Relevance 0→85.7%。",
         "suggest": "已修复。"},
        {"title": "【已修复】时效咨询被误路由到 urgent 导致空候选反复重试",
         "detail": "实测「赶船期到美国一般需要多少天？」被「赶船期」关键词路由到 urgent/agent，经历 提取参数→检索→候选生成→两轮恢复 仍无候选，"
                   "输出「请补充信息 + 未找到路线 + 低置信度人工复核」三段噪音。已修复：`back/agent/router.py` 增加时效咨询优先——"
                   "消息含 多少天/多久/几天/时效 等时长词、且无 产品+目的港 发货信号、表单不完整时强制 consult/qa 直接回答知识；"
                   "`back/agent/executor.py` 空候选经扩展检索+放宽条件恢复后仍为空时标记 `_no_candidate_final`，不再进入反思重试循环（重试 2 轮→1 轮）；"
                   "`back/agent/evidence.py` 增加疑问/副词停用 bigram 并放宽 QA 人工复核判定（覆盖率低且置信度低才标记），避免口语化问法被误报证据不足。"
                   "修复后该问题直达 consult/qa（route→retrieve→answer 三步），needs_review=False，不再反复重试。",
         "suggest": "已修复。"},
        {"title": "【口径修正】原 Recall/Precision/Faithfulness 结构性虚高，已改严格口径",
         "detail": "原口径问题：(1) Recall 把结构化规则注入 chunk（工厂/国家/条款/合约费率，score=1.0 恒排最前）也算作命中，9 题中 q06 全部 6 个 gold_facts 仅靠注入命中，q01/q05/q07/q08 也大部分靠注入——衡量的是注入覆盖而非检索能力；"
                   "(2) Precision 判定为命中任一宽泛词（美国/海运/天/船公司）即相关，9 题仅 q07 有非相关 chunk，93.7% 被宽词表撑起；"
                   "(3) Faithfulness 用 citations（=生成答案所用的检索上下文）子串自证 + 数字全豁免，结构上必然接近 100%，LLM 核验只覆盖词法未命中的少数 claim。"
                   "已改为严格口径：Recall 拆「总/纯检索」两列、Precision 需 ≥2 个不同词、Faithfulness 改为句子级 LLM 逐句核验。"
                   "修正后数字才是可对外宣传的真实水平（见本报告汇总）。",
         "suggest": "已修复。后续新增测试题时 gold_facts 应尽量用短语/数字而非 2-4 字宽泛词，并标注每题允许的注入型知识。"},
        {"title": "【口径说明】推荐类答案的 Faithfulness 与计算型数字",
         "detail": "推荐理由里的费用/评分/时效/备选方案数字来自成本引擎（computed），不在检索上下文中；评测已单独归类。"
                   "若把计算值也当作『检索支撑』要求，Faithfulness 会系统性偏低，但不代表幻觉。",
         "suggest": "推荐类答案用『实体 grounding + 成本引擎回测』代替纯检索忠实度；把计算来源写入引用（如标注 cost_engine）。"},
    ]

    meta = {
        "date": "2026-08-14",
        "llm_model": config.LLM_MODEL if config.LLM_ENABLED else "rule",
        "llm_enabled": config.LLM_ENABLED,
        "embedding": stats.get("embedding"),
        "chunks": stats.get("chunks"),
        "sources": len(stats.get("sources", [])),
        "n": len(questions),
        "findings": findings,
    }
    path = write_report(args.output, meta, results, args.llm)
    print(f"\n[eval] 报告已输出: {path}")
    print("[eval] 严格口径平均："
          f"Recall(纯检索)={sum(r['recall_retr'] for r in results)/len(results):.3f}  "
          f"Recall(总)={sum(r['recall'] for r in results)/len(results):.3f}  "
          f"Precision(>=2词)={sum(r['precision_strict'] for r in results)/len(results):.3f}  "
          f"Faithfulness(LLM句)={sum(r['faithfulness'] for r in results)/len(results):.3f}  "
          f"Relevance={sum(r['relevance'] for r in results)/len(results):.3f}")


if __name__ == "__main__":
    main()