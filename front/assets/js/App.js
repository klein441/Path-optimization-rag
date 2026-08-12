/**
 * 根组件
 */
import OrderForm from './components/OrderForm.js';
import ResultsPanel from './components/ResultsPanel.js';

export default {
    components: { OrderForm, ResultsPanel },
    methods: {
        logout() {
            window.location.href = '/';
        },
    },
    template: `
    <header class="app-header">
      <div class="header-inner">
        <div class="header-left">
          <div class="logo-badge">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>
          </div>
          <div>
            <div class="header-title">物流运输路径智能优化系统</div>
            <div class="header-sub">Logistics Route Optimization · Powered by LLM</div>
          </div>
        </div>
        <div class="header-right">
          <div class="status-dot">系统正常运行</div>
          <div class="header-stat"><b>9</b><span>生产基地</span></div>
          <div class="header-stat"><b>4</b><span>出口港口</span></div>
          <div class="header-stat"><b>50+</b><span>目的港</span></div>
          <button type="button" class="logout-btn" @click="logout">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
            退出登录
          </button>
        </div>
      </div>
    </header>

    <main class="app-main">
      <OrderForm />
      <ResultsPanel />
    </main>

    `,
};
