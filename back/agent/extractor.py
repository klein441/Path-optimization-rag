"""
自然语言 → 结构化推荐参数抽取（NL2Form）

规则通道（产品/国家/港口/数量/偏好关键词）+ LLM 通道（LLM_ENABLED 时结构化抽取）
LLM 结果优先，规则结果兜底；只填充缺失字段，不覆盖用户已填参数。
"""
import re

import config

# ===== 规则通道映射 =====
PRODUCT_KEYWORDS = [
    ("丁腈", "丁腈手套"),
    ("pvc", "PVC手套"),
    ("pe", "PE产品"),
    ("乳胶", "乳胶手套"),
]

COUNTRY_KEYWORDS = [
    ("美国", "美国"), ("加拿大", "加拿大"), ("墨西哥", "墨西哥"),
    ("德国", "德国"), ("英国", "英国"), ("法国", "法国"), ("荷兰", "荷兰"),
    ("比利时", "比利时"), ("意大利", "意大利"), ("西班牙", "西班牙"),
    ("波兰", "波兰"), ("瑞典", "瑞典"), ("日本", "日本"), ("韩国", "韩国"),
    ("新加坡", "新加坡"), ("泰国", "泰国"), ("越南", "越南"),
    ("印度尼西亚", "印度尼西亚"), ("菲律宾", "菲律宾"),
    ("澳大利亚", "澳大利亚"), ("新西兰", "新西兰"),
    ("阿联酋", "阿联酋"), ("沙特阿拉伯", "沙特阿拉伯"), ("印度", "印度"),
    ("巴西", "巴西"), ("阿根廷", "阿根廷"), ("智利", "智利"),
    ("南非", "南非"), ("埃及", "埃及"), ("土耳其", "土耳其"),
]

# 港口 -> (运抵国, 标准目的港)
PORT_MAP = {
    "洛杉矶": ("美国", "洛杉矶/LOS ANGELES"),
    "长滩": ("美国", "长滩/LONG BEACH"),
    "纽约": ("美国", "纽约/NEW YORK"),
    "温哥华": ("加拿大", "温哥华/VANCOUVER"),
    "汉堡": ("德国", "汉堡/HAMBURG"),
    "鹿特丹": ("荷兰", "鹿特丹/ROTTERDAM"),
    "安特卫普": ("比利时", "安特卫普/ANTWERP"),
    "悉尼": ("澳大利亚", "悉尼/SYDNEY"),
    "墨尔本": ("澳大利亚", "墨尔本/MELBOURNE"),
    "东京": ("日本", "东京/TOKYO"),
    "釜山": ("韩国", "釜山/BUSAN"),
    "新加坡": ("新加坡", "新加坡/SINGAPORE"),
    "海防": ("越南", "海防/HAIPHONG"),
    "迪拜": ("阿联酋", "迪拜/DUBAI"),
    "桑托斯": ("巴西", "桑托斯/SANTOS"),
    "圣保罗": ("巴西", "桑托斯/SANTOS"),
}
PORT_NAMES = list(PORT_MAP.keys())

# 数量单位 -> 千支系数（"1万支" = 10 千支）
_GLOVE_FACTOR = {"万": 10.0, "千": 1.0, "百": 0.1, "": 0.001}

_TRANSPORT_KEYWORDS = [
    (("划算", "便宜", "成本", "省钱", "低价"), "cost"),
    (("加急", "快", "时效", "赶船", "赶"), "time"),
    (("稳定",), "stable"),
]

_QTY_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(万|千|百)?\s*(支|只|双|箱|柜|柜子)")


def extract_params(message, input_data=None, llm_client=None, overwrite=False):
    """从自然语言抽取参数并合并到 input_data

    :param overwrite: True 时允许规则通道（消息中显式实体）覆盖已有参数，
                      用于多轮 follow_up（如“那发到纽约呢”更新目的港）
    :return: (merged_input, meta) — meta 含 rule/llm 抽取结果与新增字段 added
    """
    merged = dict(input_data or {})
    message = str(message or "").strip()

    rule = _extract_by_rules(message)
    llm = {}
    if llm_client is not None and config.LLM_ENABLED:
        llm = _extract_by_llm(llm_client, message)

    added = {}
    # 规则通道：消息中显式出现的实体（overwrite 时覆盖历史参数）
    for k, v in rule.items():
        if v in (None, "", 0) or k == "gloveUnit":
            continue
        if overwrite or not merged.get(k):
            merged[k] = v
            added[k] = v
    # LLM 通道：只填充缺失字段，不覆盖
    for k, v in llm.items():
        if v in (None, "", 0) or merged.get(k):
            continue
        if k == "gloveUnit" and v and v != "千支":
            # 统一换算为千支
            factor = {"万支": 10.0, "千支": 1.0, "万": 10.0, "千": 1.0}.get(str(v), 1.0)
            if merged.get("gloveQty"):
                merged["gloveQty"] = round(merged["gloveQty"] * factor, 2)
            v = "千支"
        merged[k] = v
        added[k] = v

    return merged, {"rule": rule, "llm": llm, "added": added}


def _extract_by_rules(message):
    low = message.lower()
    out = {}
    for kw, prod in PRODUCT_KEYWORDS:
        if kw in low:
            out["productType"] = prod
            break
    for name, cn in COUNTRY_KEYWORDS:
        if name in message:
            out["destCountry"] = cn
            break
    for port, (cn, std) in PORT_MAP.items():
        if port in message:
            out["destPort"] = std
            out.setdefault("destCountry", cn)
            break
    m = _QTY_RE.search(message)
    if m:
        num = float(m.group(1))
        unit = m.group(2) or ""
        count_unit = m.group(3) or ""
        if count_unit in ("箱", "柜", "柜子"):
            out["boxCount"] = int(num)
        else:
            out["gloveQty"] = round(num * _GLOVE_FACTOR[unit], 2)
            out["gloveUnit"] = "千支"
    for kws, pref in _TRANSPORT_KEYWORDS:
        if any(k in message for k in kws):
            out["transportPref"] = pref
            break
    return out


def _extract_by_llm(client, message):
    """LLM 结构化抽取（温度 0，仅返回 JSON）"""
    system = "你是物流参数抽取器，只输出 JSON，不要输出任何其他内容。"
    prompt = f"""从用户消息中抽取物流推荐参数。
可用产品: 丁腈手套 / PVC手套 / PE产品 / 乳胶手套 / 轮椅 / 小日化产品
可用运抵国: 美国/加拿大/墨西哥/德国/英国/法国/荷兰/意大利/西班牙/日本/韩国/新加坡/越南/澳大利亚/阿联酋/巴西 等
目的港示例: 洛杉矶/LOS ANGELES、汉堡/HAMBURG、悉尼/SYDNEY
数量单位说明: 系统内数量统一为千支（1万支=10千支，800箱属于箱数）

用户消息: {message}

输出 JSON（没有的字段填空字符串或 null）:
{{"productType": "", "destCountry": "", "destPort": "", "gloveQty": null, "gloveUnit": "千支", "boxCount": null, "transportPref": ""}}"""
    res = client.llm_structured_call(system, prompt, temperature=0.0, max_tokens=500)
    return res or {}