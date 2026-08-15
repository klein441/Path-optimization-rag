/**
 * RAG 智能问答页 — 物流知识助手
 * 对接：/api/chat（对话式推荐/问答）、/api/kb/search（检索）、/api/kb/stats（统计）、/api/kb/rebuild（重建索引）
 */
const $id = (id) => document.getElementById(id);

const SUGGESTIONS = [
    '哪些工厂生产丁腈手套？',
    '美国线哪家船公司最便宜？',
    '上海到洛杉矶 40HQ 海运费大概多少？',
    'FOB 和 DDP 有什么区别？',
    '赶船期到美国一般需要多少天？',
];

const ROUTE_LABEL = { fast: '快速路径', agent: 'Agent 路径', qa: '知识问答' };

let sessionId = 'rag' + Date.now().toString(36);
let asking = false;

function escapeHtml(s) {
    return String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function setStatus(state, text) {
    const dot = $id('statusDot');
    dot.className = 'rag-status-dot' + (state ? ' ' + state : '');
    $id('ragStatusText').textContent = text;
}

function setStats(stats) {
    const el = $id('ragStats');
    if (!stats) { el.textContent = ''; return; }
    el.textContent = '索引 ' + stats.chunks + ' chunks · ' + stats.embedding;
}

function fmtMoney(v) {
    const n = Number(v || 0);
    return '¥' + n.toLocaleString('zh-CN', { maximumFractionDigits: 0 });
}

// ===== 渲染问答条目 =====
function routeTag(route) {
    if (!route) return '';
    const label = ROUTE_LABEL[route.path] || route.path;
    return '[' + (route.intent || '') + ' · ' + label + ']';
}

function citationsHtml(citations) {
    if (!citations || citations.length === 0) return '';
    const items = citations.map((c) => {
        const tag = escapeHtml((c.chunk_type || '') + ' · ' + (c.source || ''));
        return '<div class="cite">' + tag + ' — ' + escapeHtml(c.text) + '</div>';
    }).join('');
    return '<div class="sources"><div class="sources-title">引用依据（' + citations.length + '）</div>' + items + '</div>';
}

function renderCardHtml(data) {
    const p = data.primary || {};
    const cost = (p.cost && p.cost.total_cny) || 0;
    const days = (p.timeline && p.timeline.total_days) || 0;
    const factory = p.factory_short || p.factoryShort || '';
    const parts = [
        '<div class="rag-card">',
        '<div class="rag-card-head"><b>' + escapeHtml(factory || '—') + '</b>',
        '<span class="rag-card-route">' + escapeHtml(p.departurePort || '') + ' → ' + escapeHtml(p.destPort || '') + '</span></div>',
        '<div class="rag-card-meta">',
        '<span>条款 ' + escapeHtml(p.tradeTerm || '—') + '</span>',
        '<span>箱型 ' + escapeHtml(p.boxType || '—') + '</span>',
        '<span>评分 ' + escapeHtml(String(p.score == null ? '' : p.score)) + '/100</span>',
        '<span>' + fmtMoney(cost) + '</span>',
        '<span>时效 ' + days + ' 天</span>',
        '</div>',
    ];
    const reason = data.reasoning || '';
    if (reason) parts.push('<div class="rag-card-reason">' + escapeHtml(reason) + '</div>');
    if (data.logId) {
        parts.push('<div class="rag-card-fb">' +
            '<button type="button" class="rag-fb" data-logid="' + escapeHtml(String(data.logId)) +
            '" data-action="confirm" data-cost="' + escapeHtml(String(cost)) + '">确认方案</button>' +
            '<button type="button" class="rag-fb" data-logid="' + escapeHtml(String(data.logId)) +
            '" data-action="modify" data-cost="' + escapeHtml(String(cost)) + '">费用不准</button>' +
            '</div>');
    }
    parts.push('</div>');
    return parts.join('');
}

function renderMessage(data) {
    let html = '';
    if (data.requires_clarification && data.clarify_question) {
        html += '<div class="rag-clarify">需要补充信息：' + escapeHtml(data.clarify_question) + '</div>';
    }
    if (data.primary) {
        html += renderCardHtml(data);
    } else if (data.answer) {
        html += escapeHtml(data.answer).replace(/\n/g, '<br>');
    } else {
        html += escapeHtml(data.error || '未获取到有效回答，请换个问法。');
    }
    if (data.route) {
        html += '<div class="rag-route-tag">' + escapeHtml(routeTag(data.route)) + '</div>';
    }
    if (data.session_context && data.session_context.params && Object.keys(data.session_context.params).length > 0) {
        const ptext = Object.entries(data.session_context.params)
            .map(([k, v]) => k + '=' + v).join(' · ');
        html += '<div class="rag-session">已记住：' + escapeHtml(ptext) + '</div>';
    }
    if (data.needs_review) {
        const pct = Math.round((data.confidence || 0) * 100);
        html += '<div class="rag-review">⚠ 置信度较低（' + pct + '%），建议人工复核' +
            (data.review_reason ? '：' + escapeHtml(data.review_reason) : '') + '</div>';
    }
    if (data.confidence != null && data.evidence_coverage != null) {
        const cov = Math.round(data.evidence_coverage * 100);
        const conf = Math.round(data.confidence * 100);
        const missing = (data.evidence && data.evidence.missing && data.evidence.missing.length)
            ? ' · 缺证据：' + escapeHtml(data.evidence.missing.join('、')) : '';
        html += '<div class="rag-evidence">证据覆盖率 ' + cov + '% · 置信度 ' + conf + '%' + missing + '</div>';
    }
    if (data.citations && data.citations.length > 0) {
        html += citationsHtml(data.citations);
    }
    return html;
}

function addQaItem(question, html, loading) {
    const list = $id('qaList');
    list.querySelector('.rag-qa-empty')?.remove();
    const item = document.createElement('div');
    item.className = 'qa-item';
    if (loading) item.classList.add('loading');
    const q = document.createElement('div');
    q.className = 'q';
    q.textContent = question;
    const a = document.createElement('div');
    a.className = 'a';
    a.innerHTML = html;
    item.appendChild(q);
    item.appendChild(a);
    list.appendChild(item);
    list.scrollTop = list.scrollHeight;
    return item;
}

// ===== 提问 =====
async function ask(question) {
    question = (question || '').trim();
    if (!question || asking) return;
    const input = $id('questionInput');
    input.value = '';
    asking = true;
    $id('askBtn').disabled = true;

    addQaItem(question, '正在检索物流知识库并生成回答…', true);
    try {
        const resp = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: question, form: {}, sessionId: sessionId }),
        });
        const data = await resp.json();
        if (!data.success) throw new Error(data.error || 'HTTP ' + resp.status);
        addQaItem(question, renderMessage(data.data));
    } catch (e) {
        addQaItem(question, escapeHtml('请求失败：' + (e.message || e)));
    } finally {
        asking = false;
        $id('askBtn').disabled = false;
    }
}

// ===== 初始化 =====
async function initStats() {
    try {
        const resp = await fetch('/api/kb/stats');
        const data = await resp.json();
        if (data.success) {
            setStats(data.data);
            setStatus('ok', '检索库就绪 · 基于已索引资料回答');
        } else {
            setStatus('err', '检索库状态未知');
        }
    } catch (e) {
        setStatus('err', '无法连接服务');
    }
}

async function postFeedback(payload) {
    const resp = await fetch('/api/recommendation/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });
    return resp.json();
}

document.addEventListener('click', async (e) => {
    const btn = e.target.closest('.rag-fb');
    if (!btn) return;
    const logId = Number(btn.dataset.logid);
    const action = btn.dataset.action;
    const cost = Number(btn.dataset.cost || 0);
    btn.disabled = true;
    try {
        if (action === 'confirm') {
            await postFeedback({ logId: logId, action: 'confirm' });
            btn.textContent = '已确认 ✓';
        } else if (action === 'modify') {
            const total = prompt('实际总费用（CNY）是多少？（用于费用修正反馈）');
            if (total === null) { btn.disabled = false; return; }
            const t = Number(total);
            if (!isFinite(t) || t <= 0) { btn.disabled = false; return; }
            await postFeedback({ logId: logId, action: 'modify', deltaCost: Math.round((t - cost) * 100) / 100 });
            btn.textContent = '已反馈 ✓';
        }
    } catch (err) {
        btn.disabled = false;
        alert('反馈提交失败：' + (err.message || err));
    }
});

function bindEvents() {
    $id('askForm').addEventListener('submit', (e) => {
        e.preventDefault();
        ask($id('questionInput').value);
    });
    $id('clearBtn').addEventListener('click', () => {
        const list = $id('qaList');
        list.innerHTML = '<div class="rag-qa-empty">输入问题开始提问，或从下方建议中选择。</div>';
    });
    $id('rebuildBtn').addEventListener('click', async () => {
        const btn = $id('rebuildBtn');
        btn.disabled = true;
        setStatus('', '正在重建索引…');
        try {
            const resp = await fetch('/api/kb/rebuild', { method: 'POST' });
            const data = await resp.json();
            if (data.success) {
                setStats(data.data);
                setStatus('ok', '索引已重建 · 基于已索引资料回答');
            } else {
                setStatus('err', '索引重建失败：' + (data.error || ''));
            }
        } catch (e) {
            setStatus('err', '索引重建请求失败：' + (e.message || e));
        } finally {
            btn.disabled = false;
        }
    });

    const wrap = $id('suggestions');
    SUGGESTIONS.forEach((s) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'rag-suggestion';
        btn.textContent = s;
        btn.addEventListener('click', () => ask(s));
        wrap.appendChild(btn);
    });
}

document.addEventListener('DOMContentLoaded', () => {
    bindEvents();
    initStats();
});