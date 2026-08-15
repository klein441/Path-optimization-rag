"""
Agent 执行器 — 规划-执行-反思 循环（轻量 AgentExecutor，不依赖 LangGraph）

流程：
  Router 分类 -> 快速路径 / 纯问答 / Agent 多步
  Agent 多步：Planner 生成计划 -> 工具循环 -> LLM 选优 -> Reflector 质检
  -> 不通过且步数未超限：追加恢复步骤重跑 -> 收敛到规则引擎结果
"""
import config
from agent.router import QueryRouter
from agent.planner import Planner
from agent.reflector import Reflector
from agent.evidence import EvidenceScorer
from session_store import get_session_store
from agent.tools import get_tool_registry, ToolContext
from llm_client import LLMClient


class AgentExecutor:
    """自适应 Agent 执行器"""

    _instance = None

    def __new__(cls, llm_client=None, retriever=None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, llm_client=None, retriever=None):
        if self._initialized:
            return
        self.router = QueryRouter()
        self.planner = Planner()
        self.reflector = Reflector()
        self.evidence = EvidenceScorer()
        self.session = get_session_store()
        self.registry = get_tool_registry()
        self.ctx = ToolContext()
        self.llm = llm_client or self.ctx.llm
        self.router.llm = self.llm
        self.retriever = retriever or self.ctx.retriever
        self._initialized = True

    # ===== 主入口 =====
    def run(self, input_data=None, message="", session_id=None):
        input_data = input_data or {}
        message = str(message or "").strip()

        # 会话记忆：历史轮确认/抽取的参数作为默认值（当前消息/表单优先）
        session = self.session.get(session_id) if session_id else None
        if session and session.get("params"):
            input_data = {**session["params"], **input_data}

        route = self.router.classify(message=message, input_data=input_data, session_id=session_id)

        # 自然语言推荐：用参数抽取器补全/覆盖结构化字段（产品/国家/港口/数量/偏好）
        # 首轮：输入不完整才抽取（补全）；后续轮（有会话记忆）：始终抽取，允许规则覆盖显式实体
        has_session = bool(session and session.get("params"))
        extraction = None
        trace = []
        if message and route["intent"] != "consult" and (not self._has_complete_input(input_data) or has_session):
            from agent.extractor import extract_params
            input_data, extraction = extract_params(message, input_data, llm_client=self.llm,
                                                    overwrite=has_session)
            trace.append({"step": "extract_params", "ok": True,
                          "added": list((extraction or {}).get("added", {}).keys())})
            route = self.router.classify(message=message, input_data=input_data, session_id=session_id)
            # 补全后仍缺关键字段 -> 归为自然语言推荐，走 Agent 路径
            if route["path"] == "fast" and not self._has_complete_input(input_data):
                route = {**route, "path": "agent", "intent": "natural_recommend"}

        state = {
            "input": input_data,
            "message": message,
            "session_id": session_id,
            "session_context": session,
            "route": route,
            "extraction": extraction,
            "candidates": [],
            "retrieval": [],
            "trace": trace,
            "steps": 0,
            "result": None,
        }

        if route["path"] == "qa":
            result = self._run_qa(state)
        elif route["path"] == "fast":
            result = self._run_fast(state)
        else:
            result = self._run_agent(state)

        self._save_session(session_id, input_data, extraction, message, result, state)
        return result

    def _save_session(self, session_id, input_data, extraction, message, result, state):
        """把本轮参数/结果写入会话记忆，并回填给前端展示"""
        if not session_id:
            return
        try:
            merged = dict(input_data)
            if extraction and extraction.get("added"):
                merged.update(extraction["added"])
            sess = self.session.update(session_id, merged, message, result=result)
            labels = {"productType": "产品", "destCountry": "运抵国", "destPort": "目的港",
                      "gloveQty": "数量(千支)", "boxCount": "箱数", "transportPref": "偏好"}
            shown = {labels.get(k, k): v for k, v in merged.items() if k in labels and v not in (None, "")}
            result["session_context"] = {
                "params": shown,
                "turns": len(sess.get("history", [])) if sess else 0,
            }
        except Exception as e:
            print(f"[会话记忆] 保存失败: {e}")

    @staticmethod
    def _has_complete_input(input_data):
        # 快速路径要求：目的地 + 目的港 + 数量（千支或箱数）齐全
        return bool(input_data.get("destCountry")) and bool(input_data.get("destPort")) \
            and bool(input_data.get("gloveQty") or input_data.get("boxCount"))

    # ===== 快速路径（简单查询）：规则 + 检索增强 + 单次 LLM =====
    def _run_fast(self, state):
        route = state["route"]
        input_data = state["input"]
        state["trace"].append({
            "step": "route",
            "path": "fast",
            "intent": route["intent"],
            "profile": route["profile"],
        })

        retrieval = self.retriever.retrieve(
            query=Planner._query_text(state),
            input_data=input_data,
            profile=route["profile"],
        )
        state["retrieval"] = retrieval
        state["trace"].append({"step": "retrieve_knowledge", "ok": True, "hits": len(retrieval)})

        result = self.llm.recommend(input_data)
        state["result"] = result
        self._attach_meta(state, result, route)
        return result

    # ===== 纯知识问答路径 =====
    def _run_qa(self, state):
        route = state["route"]
        message = state["message"]
        state["trace"].append({"step": "route", "path": "qa", "intent": route["intent"]})

        retrieval = self.retriever.retrieve(query=message, top_k=10)
        state["retrieval"] = retrieval
        state["trace"].append({"step": "retrieve_knowledge", "ok": True, "hits": len(retrieval)})

        context = self.retriever.retrieve_text(query=message, top_k=10, max_chars=5000)
        # 会话记忆：上一轮推荐摘要注入上下文，支持“这个方案/那趟船”类追问
        last = (state.get("session_context") or {}).get("last_result")
        if last and last.get("factory"):
            context = ("上一轮推荐：工厂 %s，起运港 %s，目的港 %s，总费用 ¥%s，时效 %s 天。\n"
                       % (last["factory"], last.get("origin", ""), last.get("dest", ""),
                          last.get("cost_cny", ""), last.get("days", ""))) + context
        answer = self.llm.answer_query(message, context) if config.LLM_ENABLED else {
            "answer": (context[:800] or "暂未检索到相关知识，请尝试更明确的问题。"),
            "source": "rule",
        }
        state["trace"].append({"step": "answer_query", "ok": True})

        result = {
            "answer": answer.get("answer", ""),
            "source": answer.get("source", "rule"),
            "citations": self._citations(retrieval, limit=8),
            "agent_trace": state["trace"],
            "route": {"intent": route["intent"], "path": "qa", "complexity": route["complexity"],
                      "routed_by": route.get("routed_by", "keyword"),
                      "confidence": route.get("confidence")},
        }
        state["result"] = result
        self._attach_evidence(state, result)
        return result

    # ===== Agent 多步路径（复杂查询）=====
    def _run_agent(self, state):
        route = state["route"]
        input_data = state["input"]
        state["trace"].append({
            "step": "route",
            "path": "agent",
            "intent": route["intent"],
            "profile": route["profile"],
        })

        # 1) 规划
        plan = self.planner.build_plan(state)

        # 2) 执行计划
        for step in plan:
            if not self._step_guard(state):
                break
            state["steps"] += 1
            res = self.registry.execute(step["tool"], step.get("args"))
            entry = {"step": step["tool"], "ok": res["ok"], "reason": step.get("reason", "")}
            state["trace"].append(entry)
            if res["ok"]:
                state[step["output_key"]] = res["result"]
            else:
                entry["error"] = res.get("error")

        # 3) 候选为空 -> 反思恢复（扩展检索 + 放宽条件重生成）
        candidates = state.get("candidates") or []
        if not candidates and self._step_guard(state):
            state["steps"] += 1
            state["trace"].append({"step": "recovery", "ok": True, "reason": "候选为空，扩展检索后重试"})
            retrieval = self.retriever.retrieve(
                query=Planner._query_text(state),
                input_data=input_data,
                profile={**route["profile"], "top_k": max(12, route["profile"].get("top_k", 8) + 6),
                         "query_expansion": True},
            )
            state["retrieval"] = retrieval
            state["trace"].append({"step": "retrieve_knowledge_recovered", "ok": True, "hits": len(retrieval)})
            relaxed = dict(input_data)
            relaxed.setdefault("tradePref", "auto")
            # 保留 transportPref（用户意图优先，恢复时不做覆盖）
            candidates = self.llm._generate_candidates(relaxed)
            state["candidates"] = candidates
            state["trace"].append({"step": "generate_candidates_recovered", "ok": True, "hits": len(candidates)})
            if not candidates:
                # 扩展检索 + 放宽条件后仍无候选：问题本身缺关键参数/无报价，再重试无意义，直接收敛
                state["_no_candidate_final"] = True

        # 4) 生成最终推荐（LLM 选优 + 质检，或规则兜底）
        if not candidates:
            result = {
                "error": "未找到符合条件的路线",
                "answer": self._no_candidate_hint(state),
                "source": "rule",
            }
        elif config.LLM_ENABLED:
            result = (self.llm._compare_recommend(input_data, candidates, state["message"])
                      if route["intent"] == "compare" else None)
            if result is None:
                result = self.llm._call_llm(input_data, candidates)
            if not result:
                result = self.llm._rule_based_recommend(input_data, candidates)
                result["source"] = "rule_engine"
            else:
                result.setdefault("source", "llm")
        else:
            result = self.llm._rule_based_recommend(input_data, candidates)
            result["source"] = "rule_engine"
        state["result"] = result

        # 5) 反思校验 + 恢复（多轮收敛：multi_round 意图最多 3 轮，普通 1 轮）
        verdict = self.reflector.validate(state)
        self._trace_reflect(state, "reflect", verdict)
        max_rounds = 3 if route["profile"].get("multi_round") else 1
        round_no = 0
        prev_ev = self.evidence.score(state)
        while ((not verdict["ok"] and verdict["can_retry"])
               or (round_no == 0 and route["profile"].get("multi_round")
                   and self._evidence_below_target(prev_ev))) \
                and self._step_guard(state) and round_no < max_rounds \
                and not state.get("_no_candidate_final"):
            round_no += 1
            state["steps"] += 1
            state["trace"].append({"step": "recovery", "ok": True,
                                   "reason": f"反思不通过或证据不足，第 {round_no} 轮恢复"})
            for step in self.reflector.suggest_recovery(state):
                if not self._step_guard(state):
                    break
                state["steps"] += 1
                res = self.registry.execute(step["tool"], step.get("args"))
                state["trace"].append({"step": f"{step['tool']}_recovered", "ok": res["ok"]})
                if res["ok"] and step["output_key"] in ("candidates",):
                    state[step["output_key"]] = res["result"]
            candidates = state.get("candidates") or []
            if candidates and config.LLM_ENABLED:
                retry = (self.llm._compare_recommend(input_data, candidates, state["message"])
                         if route["intent"] == "compare" else None)
                if retry is None:
                    retry = self.llm._call_llm(input_data, candidates)
                if retry:
                    retry.setdefault("source", "llm")
                    result = retry
            state["result"] = result
            verdict = self.reflector.validate(state)
            step_name = "reflect_recovered" if round_no == 1 else f"reflect_round{round_no}"
            self._trace_reflect(state, step_name, verdict)
            cur_ev = self.evidence.score(state)
            improved = (cur_ev["confidence"] - prev_ev["confidence"] >= config.EVIDENCE_CONVERGE_EPS
                        or cur_ev["coverage"] - prev_ev["coverage"] >= config.EVIDENCE_CONVERGE_EPS)
            if not improved:
                state["trace"].append({"step": "converge_stop", "ok": True,
                                       "reason": "证据分数无提升，停止多轮检索"})
                break
            prev_ev = cur_ev

        self._attach_meta(state, result, route)
        return result

    # ===== 辅助 =====
    def _step_guard(self, state):
        return state["steps"] < config.AGENT_MAX_STEPS

    def _no_candidate_hint(self, state):
        # 空候选时的友好提示：说明已解析参数与可能原因
        added = ((state.get("extraction") or {}).get("added")) or {}
        labels = {"productType": "产品", "destCountry": "运抵国", "destPort": "目的港",
                  "gloveQty": "数量(千支)", "boxCount": "箱数", "transportPref": "偏好"}
        parts = []
        for k, v in added.items():
            if k in labels and v:
                parts.append(f"{labels[k]}={v}")
        detail = ("已从你的描述中解析：" + "，".join(parts) + "。") if parts else ""
        return ("未找到符合条件的路线。" + detail +
                "可能原因：该目的港当前无可用合约报价，或数量未命中工厂分配区间。"
                "可补充具体箱数/重量后重试。")

    def _attach_meta(self, state, result, route):
        retrieval = state.get("retrieval") or []
        result["citations"] = self._citations(retrieval, limit=8)
        result["agent_trace"] = state["trace"]
        result["retrieval_used"] = len(retrieval) > 0
        result["route"] = {"intent": route["intent"], "path": route["path"], "complexity": route["complexity"],
                           "routed_by": route.get("routed_by", "keyword"),
                           "confidence": route.get("confidence")}
        self._attach_evidence(state, result)
        return result

    def _attach_evidence(self, state, result):
        """答案级置信度 / 证据覆盖率 / 人工复核与反问澄清标记"""
        ev = self.evidence.score(state)
        result["confidence"] = ev["confidence"]
        result["evidence_coverage"] = ev["coverage"]
        result["evidence"] = {
            "supported": ev["supported"],
            "missing": ev["missing"],
            "retrieval_quality": ev["retrieval_quality"],
            "determinism": ev["determinism"],
        }
        result["needs_review"] = ev["needs_review"]
        result["review_reason"] = ev["review_reason"]
        result["requires_clarification"] = ev["requires_clarification"]
        if ev["clarify_question"]:
            result["clarify_question"] = ev["clarify_question"]

    def _evidence_below_target(self, ev):
        return ev["coverage"] < config.EVIDENCE_TARGET_COVERAGE or ev["confidence"] < config.EVIDENCE_MIN_CONFIDENCE

    @staticmethod
    def _trace_reflect(state, step_name, verdict):
        state["trace"].append({
            "step": step_name,
            "ok": verdict["ok"],
            "issues": [i["code"] for i in verdict["issues"]],
        })

    @staticmethod
    def _citations(retrieval, limit=8):
        out = []
        for c in retrieval[:limit]:
            text = str(c.get("text", ""))
            out.append({
                "chunk_id": c.get("chunk_id"),
                "source": c.get("source"),
                "chunk_type": c.get("chunk_type"),
                "score": c.get("score", 0),
                "text": text[:200] + ("..." if len(text) > 200 else ""),
                "metadata": c.get("metadata", {}),
            })
        return out


def get_executor(llm_client=None, retriever=None):
    """获取全局执行器（单例）"""
    executor = AgentExecutor(llm_client=llm_client, retriever=retriever)
    if llm_client is not None:
        executor.llm = llm_client
    if retriever is not None:
        executor.retriever = retriever
    return executor