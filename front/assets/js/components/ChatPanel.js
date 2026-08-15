/**
 * 自适应 Agentic RAG 对话面板
 * 支持：知识问答（answer）、对话式推荐（primary 路线卡片）、引用溯源（citations）
 */
import { apiChat } from '../api.js';
import { store } from '../state.js';

function escapeHtml(s) {
    return String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function buildFormPayload() {
    const f = store.form;
    return {
        customer: f.customer || '',
        orderNumber: f.orderNumber || '',
        productType: (f.productTypes || []).join(','),
        destCountry: f.destCountry || '',
        destPort: f.destPort || '',
        gloveQty: parseInt(f.gloveQty) || 0,
        gloveUnit: f.gloveUnit || '千支',
        boxCount: parseInt(f.boxes) || 1,
        weight: parseFloat(f.weight) || 0,
        volume: parseFloat(f.volume) || 0,
        cargoReady: f.cargoReady || '',
        requiredArrival: f.requiredArrival || '',
        urgent: Boolean(f.urgent),
        transportPref: f.transportPref || 'balanced',
        tradePref: f.tradePref || 'auto',
        remarks: f.remarks || '',
    };
}

const SUGGESTIONS = [
    '哪些工厂生产丁腈手套？',
    '美国到货一般要多少天？',
    '对比一下青岛和上海出发哪个划算',
];

export default {
    data() {
        return {
            open: false,
            loading: false,
            input: '',
            sessionId: 'c' + Date.now().toString(36),
            messages: [
                {
                    role: 'assistant',
                    text: '你好，我是物流智能助手。可以直接问知识问题，也可以说"帮我推荐美国路线"（将使用左侧表单参数）。',
                },
            ],
        };
    },
    computed: {
        suggestions() {
            return SUGGESTIONS;
        },
    },
    methods: {
        toggle() {
            this.open = !this.open;
        },
        useSuggestion(s) {
            this.input = s;
            this.send();
        },
        async send() {
            const text = this.input.trim();
            if (!text || this.loading) return;
            this.input = '';
            this.messages.push({ role: 'user', text: text });
            this.loading = true;
            const idx = this.messages.push({ role: 'assistant', text: '思考中...', loading: true }) - 1;
            try {
                const data = await apiChat(text, buildFormPayload(), this.sessionId);
                this.messages[idx] = {
                    role: 'assistant',
                    text: data.answer || '',
                    data: data,
                    route: data.route || null,
                    primary: data.primary || null,
                    citations: data.citations || [],
                    loading: false,
                };
            } catch (e) {
                this.messages[idx] = { role: 'assistant', text: '出错了：' + (e.message || e), loading: false };
            } finally {
                this.loading = false;
            }
        },
        routeBadge(route) {
            if (!route) return '';
            const label = { fast: '快速路径', agent: 'Agent 路径', qa: '知识问答' }[route.path] || route.path;
            return '[' + (route.intent || '') + ' · ' + label + ']';
        },
        routeCardHtml(msg) {
            const p = msg.primary || {};
            const route = p.factoryShort || p.factory_short || '';
            const cost = (p.cost && (p.cost.total_cny || p.cost.totalCny)) || 0;
            const days = (p.timeline && p.timeline.total_days) || 0;
            const parts = [
                '<div class="chat-card">',
                '<div class="chat-card-head">',
                '<b>' + escapeHtml(route || '—') + '</b>',
                '<span class="chat-card-route">' + escapeHtml(p.departurePort || '') + ' → ' + escapeHtml(p.destPort || '') + '</span>',
                '</div>',
                '<div class="chat-card-meta">',
                '<span>条款 ' + escapeHtml(p.tradeTerm || '—') + '</span>',
                '<span>箱型 ' + escapeHtml(p.boxType || '—') + '</span>',
                '<span>评分 ' + escapeHtml(String(p.score || 0)) + '/100</span>',
                '<span>总费用 ¥' + Number(cost).toLocaleString() + '</span>',
                '<span>时效 ' + days + ' 天</span>',
                '</div>',
            ];
            if (msg.text) {
                parts.push('<div class="chat-card-reason">' + escapeHtml(msg.text) + '</div>');
            } else if (msg.data && msg.data.reasoning) {
                parts.push('<div class="chat-card-reason">' + escapeHtml(msg.data.reasoning) + '</div>');
            }
            parts.push('</div>');
            return parts.join('');
        },
        citationsHtml(citations) {
            if (!citations || citations.length === 0) return '';
            const items = citations.map((c) => {
                const src = c.source || '';
                const type = c.chunk_type || '';
                return '<li><span class="chat-cite-tag">' + escapeHtml(type) + ' · ' + escapeHtml(src) + '</span> '
                    + escapeHtml(c.text) + '</li>';
            }).join('');
            return '<details class="chat-citations"><summary>引用依据（' + citations.length + '）</summary><ul>' + items + '</ul></details>';
        },
        renderMsg(msg) {
            if (msg.loading) {
                return '<div class="chat-typing">' + escapeHtml(msg.text) + '</div>';
            }
            let html = '';
            if (msg.primary) {
                html += this.routeCardHtml(msg);
            } else if (msg.text) {
                html += '<div class="chat-text">' + escapeHtml(msg.text).replace(/\n/g, '<br>') + '</div>';
            }
            if (msg.route) {
                html += '<div class="chat-route-tag">' + escapeHtml(this.routeBadge(msg.route)) + '</div>';
            }
            if (msg.citations && msg.citations.length > 0) {
                html += this.citationsHtml(msg.citations);
            }
            return html;
        },
    },
    template: `
    <div class="chat-root">
      <transition name="chat-fade">
        <div v-if="open" class="chat-panel">
          <div class="chat-panel-head">
            <div>
              <b>物流智能助手</b>
              <span class="chat-head-sub">自适应 Agentic RAG</span>
            </div>
            <button type="button" class="chat-close" @click="toggle">✕</button>
          </div>
          <div class="chat-body">
            <div v-for="(m, i) in messages" :key="i" class="chat-msg" :class="'chat-msg-' + m.role" v-html="renderMsg(m)"></div>
          </div>
          <div class="chat-suggest" v-if="!loading">
            <button v-for="s in suggestions" :key="s" type="button" class="chat-suggest-btn" @click="useSuggestion(s)">{{ s }}</button>
          </div>
          <div class="chat-input-row">
            <input v-model="input" class="chat-input" placeholder="问知识、聊需求、让我推荐…" @keyup.enter="send" :disabled="loading">
            <button type="button" class="chat-send" @click="send" :disabled="loading || !input.trim()">发送</button>
          </div>
        </div>
      </transition>
      <button type="button" class="chat-fab" @click="toggle" :title="open ? '收起' : '打开智能助手'">
        <svg v-if="!open" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
        <span v-else>✕</span>
      </button>
    </div>
    `,
};