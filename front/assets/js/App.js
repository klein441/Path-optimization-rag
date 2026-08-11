/**
 * 根组件
 */
import OrderForm from './components/OrderForm.js';
import ResultsPanel from './components/ResultsPanel.js';
import CostInfoModal from './components/CostInfoModal.js';

export default {
    components: { OrderForm, ResultsPanel, CostInfoModal },
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
        </div>
      </div>
    </header>

    <main class="app-main">
      <OrderForm />
      <ResultsPanel />
    </main>

    <CostInfoModal />
    `,
};