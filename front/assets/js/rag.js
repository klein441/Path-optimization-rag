/**
 * 物流 RAG 智能问答前端
 */

const state = {
    history: [],
    suggestions: [],
};

async function fetchJSON(url, options = {}) {
    const resp = await fetch(url, options);
    const data = await resp.json();
    if (!resp.ok || data.success === false) {
        throw new Error(data.error || '请求失败');
    }
    return data;
}

function setStatus(text, ok) {
    const dot = document.getElementById('statusDot');
    const statusText = document.getElementById('ragStatusText');
    statusText.textContent = text;
    dot.className = 'rag-status-dot ' + (ok === true ? 'ok' : ok === false ? 'err' : '');
}

function renderHistory() {
    const list = document.getElementById('qaList');
    list.innerHTML = '';
    if (!state.history.length) {
        const empty = document.createElement('div');
        empty.className = 'rag-qa-empty';
        empty.textContent = '还没有问答记录，输入问题开始体验。';
        list.appendChild(empty);
        return;
    }
    state.history.slice().reverse().forEach((item) => {
        const card = document.createElement('div');
        card.className = 'qa-item';

        const q = document.createElement('div');
        q.className = 'q';
        q.textContent = 'Q：' + item.question;

        const a = document.createElement('div');
        a.className = 'a';
        a.textContent = 'A：' + item.answer;

        const sources = document.createElement('div');
        sources.className = 'sources';
        const sourceText = (item.sources || []).map((s) => s.source || '').filter(Boolean).join('；');
        sources.textContent = '来源：' + (sourceText || '无');

        card.append(q, a, sources);
        list.appendChild(card);
    });
    list.scrollTop = list.scrollHeight;
}

function renderSuggestions() {
    const wrap = document.getElementById('suggestions');
    wrap.innerHTML = '';
    state.suggestions.slice(0, 6).forEach((text) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'rag-suggestion';
        btn.textContent = text;
        btn.addEventListener('click', () => {
            document.getElementById('questionInput').value = text;
            askQuestion(text);
        });
        wrap.appendChild(btn);
    });
}

async function refreshStatus() {
    try {
        const data = await fetchJSON('/api/rag/status');
        const d = data.data || {};
        const stats = [];
        if (d.loaded_docs) stats.push(d.loaded_docs + ' 条文档');
        if (d.chunk_count) stats.push(d.chunk_count + ' 个分块');
        document.getElementById('ragStats').textContent = stats.length ? '· ' + stats.join('，') : '';
        if (d.error) {
            setStatus('RAG 初始化失败：' + d.error, false);
        } else {
            setStatus(d.reused_vector_db ? '向量库已加载' : '向量库已就绪', true);
        }
    } catch (e) {
        setStatus(e.message, false);
    }
}

async function loadHistory() {
    const data = await fetchJSON('/api/rag/history');
    state.history = data.data || [];
    renderHistory();
}

async function loadSuggestions() {
    const data = await fetchJSON('/api/rag/suggestions');
    state.suggestions = data.data || [];
    renderSuggestions();
}

async function askQuestion(question) {
    const input = document.getElementById('questionInput');
    const text = (question || input.value || '').trim();
    if (!text) return;

    const btn = document.getElementById('askBtn');
    btn.disabled = true;
    btn.textContent = '检索中...';
    try {
        await fetchJSON('/api/rag/ask', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question: text }),
        });
        input.value = '';
        await Promise.all([loadHistory(), refreshStatus(), loadSuggestions()]);
    } catch (e) {
        alert(e.message);
    } finally {
        btn.disabled = false;
        btn.textContent = '提问';
    }
}

async function clearHistory() {
    await fetchJSON('/api/rag/history/clear', { method: 'POST' });
    await loadHistory();
}

async function rebuildIndex() {
    const btn = document.getElementById('rebuildBtn');
    btn.disabled = true;
    btn.textContent = '重建中...';
    setStatus('正在重建向量库，可能需要几分钟', true);
    try {
        await fetchJSON('/api/rag/rebuild', { method: 'POST' });
        await refreshStatus();
        alert('向量库重建完成');
    } catch (e) {
        alert(e.message);
    } finally {
        btn.disabled = false;
        btn.textContent = '重建索引';
    }
}

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('askForm').addEventListener('submit', (e) => {
        e.preventDefault();
        askQuestion();
    });
    document.getElementById('clearBtn').addEventListener('click', clearHistory);
    document.getElementById('rebuildBtn').addEventListener('click', rebuildIndex);
    loadHistory().catch(() => {});
    loadSuggestions().catch(() => {});
    refreshStatus();
});
