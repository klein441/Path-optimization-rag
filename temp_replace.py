import re

with open(r'd:\Path optimization\front\assets\app.js', 'r', encoding='utf-8') as f:
    content = f.read()

old_func_start = content.find('async function fetchOceanFreightRate() {')
if old_func_start == -1:
    print('ERROR: function not found')
    exit(1)

brace_count = 0
i = old_func_start
started = False
while i < len(content):
    if content[i] == '{':
        brace_count += 1
        started = True
    elif content[i] == '}':
        brace_count -= 1
        if started and brace_count == 0:
            old_func_end = i + 1
            break
    i += 1
else:
    print('ERROR: could not find end of function')
    exit(1)

print(f'Found function from {old_func_start} to {old_func_end}')
print(f'Old function length: {old_func_end - old_func_start} chars')

new_func = r'''async function fetchOceanFreightRate() {
    const loadingEl = document.getElementById('oceanLoading');
    const realtimeEl = document.getElementById('oceanRealtime');
    const errorEl = document.getElementById('oceanError');
    const errorDesc = document.getElementById('oceanErrorDesc');
    const refreshBtn = document.getElementById('oceanRefreshBtn');

    loadingEl.style.display = 'flex';
    realtimeEl.style.display = 'none';
    errorEl.style.display = 'none';
    refreshBtn.classList.add('loading');

    // 收集表单数据
    const productTypes = getMultiSelectValues('productTypeMulti');
    const productType = productTypes[0] || '';
    const destCountry = document.getElementById('destCountry')?.value || '';
    const boxTypes = getMultiSelectValues('boxTypeMulti');
    const effectiveBoxTypes = boxTypes.length > 0 ? boxTypes : ['40HQ'];
    const weight = document.getElementById('weight')?.value || '15000';
    const boxCount = document.getElementById('boxes')?.value || '1';
    const cargoReady = document.getElementById('cargoReady')?.value || '';
    const shipSchedule = document.getElementById('shipSchedule')?.value || '';

    let routeInfo = null;
    let origin = '';
    let destination = '';
    let factoryProvince = '';

    // 更新推荐航线信息卡片
    function updateRouteCard(factory, orig, dest) {
        const fEl = document.getElementById('routeInfoFactory');
        const oEl = document.getElementById('routeInfoOrigin');
        const dEl = document.getElementById('routeInfoDest');
        if (fEl && factory) fEl.textContent = factory;
        if (oEl && orig) oEl.textContent = orig;
        if (dEl && dest) dEl.textContent = dest;
    }

    // 查询单个箱型的合约海运费
    async function queryFreightRate(orig, dest, boxType) {
        const url = new URL('/api/freight-rate', window.location.origin);
        url.searchParams.set('origin', orig);
        url.searchParams.set('destination', dest);
        url.searchParams.set('boxType', boxType);
        const resp = await fetch(url.toString(), { cache: 'no-store' });
        const result = await resp.json();
        if (result.success && result.data) return result.data;
        throw new Error(result.error || '查询失败');
    }

    // Step 1: 获取工厂→始发港 和 运抵国→目的港
    try {
        const routeUrl = new URL('/api/route-info', window.location.origin);
        routeUrl.searchParams.set('productType', productType);
        routeUrl.searchParams.set('destCountry', destCountry);
        if (cargoReady) routeUrl.searchParams.set('cargoReady', cargoReady);
        if (shipSchedule) routeUrl.searchParams.set('shipSchedule', shipSchedule);
        routeUrl.searchParams.set('boxType', effectiveBoxTypes[0]);

        const routeResp = await fetch(routeUrl.toString());
        const routeResult = await routeResp.json();

        if (routeResult.success && routeResult.data) {
            routeInfo = routeResult.data;
            origin = routeInfo.originPort;
            destination = routeInfo.destPort;
            factoryProvince = routeInfo.factoryProvince || '';
            console.log('[海运费] 路线查询成功:',
                routeInfo.factoryShort, '→', origin, '→', destination,
                '| 推荐航司:', routeInfo.recommendedShippingLine?.name || '无',
                '| 模式:', routeInfo.selectionMode);

            initLandFees(factoryProvince, 'direct');
            updateRouteCard(routeInfo.factoryShort || routeInfo.factory, origin, destination);
        } else {
            const fallback = getOceanPortsByCountry(destCountry);
            origin = fallback.origin;
            destination = fallback.destination;
            factoryProvince = fallback.province || '';
            updateRouteCard('（回退）', origin, destination);
            console.warn('[海运费] 路线查询失败，回退:', routeResult.error);
        }
    } catch (e) {
        const fallback = getOceanPortsByCountry(destCountry);
        origin = fallback.origin;
        destination = fallback.destination;
        factoryProvince = fallback.province || '';
        updateRouteCard('（回退）', origin, destination);
        console.warn('[海运费] 路线查询异常:', e.message);
    }

    // Step 2: 查询所有箱型的海运费（并行请求）
    try {
        const ratePromises = effectiveBoxTypes.map(bt => queryFreightRate(origin, destination, bt));
        const allResults = await Promise.all(ratePromises);

        const currency = allResults[0]?.currency || 'USD';
        const currencySymbol = currency === 'USD' ? '$' : (currency === 'CNY' || currency === 'RMB' ? '¥' : (currency + ' '));

        // 汇总所有箱型的报价
        const totalMin = allResults.reduce((s, r) => s + (r.minRate || 0), 0);
        const totalMax = allResults.reduce((s, r) => s + (r.maxRate || 0), 0);
        const totalMedian = allResults.reduce((s, r) => s + (r.medianRate || 0), 0);
        const totalAvg = allResults.reduce((s, r) => s + (r.avgRate || 0), 0);

        document.getElementById('oceanMinRate').textContent = currencySymbol + Math.round(totalMin).toLocaleString();
        document.getElementById('oceanMedianRate').textContent = currencySymbol + Math.round(totalMedian).toLocaleString();
        document.getElementById('oceanMaxRate').textContent = currencySymbol + Math.round(totalMax).toLocaleString();

        const boxSummary = effectiveBoxTypes.length > 1
            ? effectiveBoxTypes.join(' + ')
            : (allResults[0]?.boxType || effectiveBoxTypes[0]);
        document.getElementById('oceanRouteInfo').textContent = `${origin} → ${destination} · ${boxSummary}`;

        const totalQuotes = allResults.reduce((s, r) => s + (r.quoteCount || 0), 0);
        const totalValid = allResults.reduce((s, r) => s + (r.validQuoteCount || 0), 0);
        const totalExpired = totalQuotes - totalValid;
        const transitInfo = [];
        if (routeInfo && routeInfo.transitDays) {
            transitInfo.push(`${routeInfo.transitDays}天转运`);
        }
        transitInfo.push(`${totalValid}家航司报价` + (totalExpired > 0 ? `（${totalExpired}家已过期）` : ''));
        if (effectiveBoxTypes.length > 1) {
            transitInfo.push(`${effectiveBoxTypes.length}种箱型汇总`);
        }
        document.getElementById('oceanTransitInfo').textContent = transitInfo.join(' · ');

        const fetchTime = new Date().toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
        const fileInfo = allResults[0]?.fileUpdate ? `📄 ${allResults[0].fileUpdate.split(' ')[0]}` : '📄 合约表';
        document.getElementById('oceanFetchedAt').textContent = fileInfo + ' · ' + fetchTime;

        // 渲染船公司合约报价卡片（按箱型分组）
        const quotesListEl = document.getElementById('oceanQuotesList');
        const quotesGridEl = document.getElementById('oceanQuotesGrid');
        let hasAnyQuotes = false;
        let cardsHtml = '';

        allResults.forEach((r, idx) => {
            const bt = effectiveBoxTypes[idx];
            const quotes = r.quotes || [];
            if (quotes.length === 0) return;
            hasAnyQuotes = true;

            if (effectiveBoxTypes.length > 1) {
                cardsHtml += `<div style="grid-column:1/-1;font-size:0.75rem;font-weight:700;color:var(--accent);margin:0.3rem 0.2rem 0.1rem;padding-bottom:0.2rem;border-bottom:1px dashed var(--rule)">📦 ${bt} · ${currencySymbol}${Math.round(r.medianRate || 0).toLocaleString()} 中位价</div>`;
            }

            quotes.slice(0, effectiveBoxTypes.length > 1 ? 4 : 8).forEach(q => {
                const rateVal = Number(q.rate).toLocaleString();
                const period = q.effectiveFrom || q.effectiveTo
                    ? `${q.effectiveFrom || '…'} 至 ${q.effectiveTo || '…'}` : '';
                const validBadge = q.isValid
                    ? '<span class="ocean-quote-valid yes">有效</span>'
                    : '<span class="ocean-quote-valid no">过期</span>';
                const note = q.note ? `<div style="margin-top:4px;color:#94a3b8;font-size:0.7rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${q.note.replace(/"/g, '&quot;')}">${q.note}</div>` : '';
                cardsHtml += `
                  <div class="ocean-quote-card ${q.isValid ? 'valid' : ''}">
                    <div class="ocean-quote-head">
                      <span class="ocean-quote-carrier">${q.carrier || 'N/A'}</span>
                      <span class="ocean-quote-rate">${currencySymbol}${rateVal}</span>
                    </div>
                    <div class="ocean-quote-meta">${validBadge}${period ? ' · ' + period : ''}</div>
                    ${note}
                  </div>`;
            });
        });

        if (hasAnyQuotes) {
            quotesGridEl.innerHTML = cardsHtml;
            quotesListEl.style.display = 'block';
        } else {
            quotesListEl.style.display = 'none';
        }

        if (routeInfo && routeInfo.recommendedShippingLine) {
            const rec = routeInfo.recommendedShippingLine;
            const lineEl = document.getElementById('oceanShippingLine');
            if (lineEl) {
                lineEl.textContent = `推荐航司: ${rec.name} (${rec.code}) · ${rec.transit_days}天 · ${rec.frequency}`;
            }
        } else if (hasAnyQuotes) {
            const firstQuote = allResults[0]?.quotes?.find(q => q.isValid) || allResults[0]?.quotes?.[0];
            const lineEl = document.getElementById('oceanShippingLine');
            if (lineEl && firstQuote) {
                lineEl.textContent = `最低报价航司: ${firstQuote.carrier} · ${currencySymbol}${Number(firstQuote.rate).toLocaleString()}`;
            }
        }

        if (routeInfo) {
            const fEl = document.getElementById('oceanFactoryTag');
            if (fEl) fEl.textContent = `${routeInfo.factoryShort} · ${origin}`;
            const fcEl = document.getElementById('oceanFCLTag');
            if (fcEl) fcEl.textContent = `${routeInfo.cargoType} · ${effectiveBoxTypes.length > 1 ? effectiveBoxTypes.length + '种箱型' : (routeInfo.isFCL ? 'FCL整箱' : 'LCL拼箱')}`;
        }

        loadingEl.style.display = 'none';
        errorEl.style.display = 'none';
        realtimeEl.style.display = 'block';

        const rateCny = currency === 'USD' ? (totalMedian * 7.2) : totalMedian;
        const cny = Math.round(rateCny * 100) / 100;
        const oceanFeeInput = document.getElementById('oceanFee');
        const currentVal = parseFloat(oceanFeeInput.value);
        const defaultValues = [2500, 900, 0];
        if (!oceanFeeInput.value || defaultValues.some(v => Math.abs(currentVal - v) < 0.01)) {
            oceanFeeInput.value = cny;
            feeData.ocean.fee = cny;
            updateGrandTotal();
        }

        console.log('[海运费] 合约报价成功:', origin, '→', destination,
            `箱型:${effectiveBoxTypes.join(',')}`,
            `min=${currencySymbol}${Math.round(totalMin)}`,
            `median=${currencySymbol}${Math.round(totalMedian)}`,
            `max=${currencySymbol}${Math.round(totalMax)}`,
            routeInfo ? `| 工厂=${routeInfo.factoryShort}` : '');
    } catch (e) {
        console.error('[海运费] 合约报价获取失败:', e);
        loadingEl.style.display = 'none';
        realtimeEl.style.display = 'none';
        errorEl.style.display = 'block';
        errorEl.textContent = '合约报价未匹配';
        errorDesc.textContent = `无法获取 ${effectiveBoxTypes.join(', ')} 从 ${origin} 到 ${destination} 的海运费。请检查合约数据或选择其他路线。`;
        refreshBtn.classList.remove('loading');
    }
}'''

new_content = content[:old_func_start] + new_func + content[old_func_end:]

with open(r'd:\Path optimization\front\assets\app.js', 'w', encoding='utf-8') as f:
    f.write(new_content)

print('SUCCESS: Function replaced successfully')
print(f'New file size: {len(new_content)} chars')