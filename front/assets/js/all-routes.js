/**
 * All Routes Price Comparison - Standalone Page
 */
(function () {
    var KEY = 'allRoutesData';
    var data = null;
    try {
        data = JSON.parse(localStorage.getItem(KEY) || 'null');
    } catch (e) {
        data = null;
    }
    var candidates = (data && Array.isArray(data.candidates)) ? data.candidates : [];
    var primary = (data && data.primary) || {};

    function isPrimaryRoute(c) {
        return (c.factoryShort || c.factory || '') === (primary.factoryShort || primary.factory || '') &&
               (c.departurePort || '') === (primary.departurePort || '') &&
               (c.destPort || '') === (primary.destPort || '');
    }
    var minCost = candidates.reduce(function (m, c) {
        var v = c.totalCostCny || 0;
        return v < m ? v : m;
    }, Infinity);

    var sortKey = 'totalCostCny';
    var sortDesc = false;

    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g, function (m) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m];
        });
    }
    function portShort(port) { return port ? String(port).split('/')[0] : '—'; }
    function sourceLabel(c) { return c.pricingSource === 'llm' ? 'LLM' : c.pricingSource === 'contract' ? "合约" : "规则"; }
    function sourceClass(c) { return c.pricingSource === 'llm' ? 'source-llm' : c.pricingSource === 'contract' ? 'source-contract' : 'source-rule'; }
    function qualityLabel(c) { return c.dataQuality === 'high' ? "高" : c.dataQuality === 'low' ? "低" : c.dataQuality === 'llm' ? 'LLM' : "中"; }
    function qualityClass(c) { return c.dataQuality === 'high' ? 'quality-high' : c.dataQuality === 'low' ? 'quality-low' : c.dataQuality === 'llm' ? 'source-llm' : 'quality-medium'; }

    function sorted() {
        var arr = candidates.slice();
        arr.sort(function (a, b) {
            var va = a[sortKey];
            var vb = b[sortKey];
            if (sortKey === 'factoryShort' || sortKey === 'tradeTerm') {
                return sortDesc ? String(vb || '').localeCompare(String(va || '')) : String(va || '').localeCompare(String(vb || ''));
            }
            return sortDesc ? ((vb || 0) - (va || 0)) : ((va || 0) - (vb || 0));
        });
        return arr;
    }

    function render() {
        var tbody = document.getElementById('arTbody');
        if (!tbody) return;
        var rows = sorted().map(function (c) {
            var isP = isPrimaryRoute(c);
            var isL = !isP && c.totalCostCny === minCost;
            var badge = isP ? '<span class="best-badge">最优</span>'
                       : isL ? '<span class="best-badge" style="background:#0891b2">最低</span>' : '';
            return '<tr>' +
                '<td class="badge-cell">' + badge + '</td>' +
                '<td class="route-cell">' + esc(c.factoryShort || c.factory) +
                    ' <span class="sep">→</span> ' + esc(portShort(c.departurePort)) +
                    ' <span class="sep">→</span> ' + esc(portShort(c.destPort)) + '</td>' +
                '<td>' + esc(c.tradeTerm || '—') + '</td>' +
                '<td class="cost-cell">¥' + Number(c.totalCostCny || 0).toLocaleString() + '</td>' +
                '<td class="days-cell">' + (c.totalDays || '?') + '天</td>' +
                '<td class="score-cell">' + (c.score || 0) + '</td>' +
                '<td><span class="source-tag ' + sourceClass(c) + '">' + sourceLabel(c) + '</span></td>' +
                '<td style="text-align:center"><span class="' + qualityClass(c) + '">' + qualityLabel(c) + '</span></td>' +
                '</tr>';
        }).join('');
        tbody.innerHTML = rows;
        var cnt = document.getElementById('arCount');
        if (cnt) cnt.textContent = "共 " + candidates.length + " 条路线";
        var emptyEl = document.getElementById('arEmpty');
        if (emptyEl) emptyEl.style.display = candidates.length ? 'none' : 'block';
        var ths = document.querySelectorAll('#arTable thead th[data-key]');
        for (var i = 0; i < ths.length; i++) {
            var ind = ths[i].querySelector('.sort-ind');
            if (ind) ind.parentNode.removeChild(ind);
            if (ths[i].getAttribute('data-key') === sortKey) {
                var sEl = document.createElement('span');
                sEl.className = 'sort-ind';
                sEl.textContent = sortDesc ? '▼' : '▲';
                ths[i].appendChild(sEl);
            }
        }
    }

    function init() {
        var ths = document.querySelectorAll('#arTable thead th[data-key]');
        for (var i = 0; i < ths.length; i++) {
            ths[i].addEventListener('click', function () {
                var k = this.getAttribute('data-key');
                if (k === 'badge') return;
                if (sortKey === k) {
                    sortDesc = !sortDesc;
                } else {
                    sortKey = k;
                    sortDesc = (k === 'factoryShort' || k === 'tradeTerm');
                }
                render();
            });
        }
        render();
    }
    init();

function goBackHome() {
    // 由首页按钮打开时：关闭当前页返回原页面；直接访问时回退到首页
    if (window.opener && !window.opener.closed) {
        try { window.opener.focus(); } catch (e) {}
        window.close();
    } else {
        location.href = 'logistics-optimizer.html';
    }
}
window.goBackHome = goBackHome;
})();
