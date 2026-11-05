(() => {
  'use strict';
  const app = document.getElementById('app');
  const data = window.LEARNING_FLOW;
  if (!data || !Array.isArray(data.paths) || !data.paths.length) {
    app.innerHTML = '<div class="empty"><h1>学习脉络暂时无法显示</h1><p>课程数据尚未生成或加载失败。</p><a href="index.html">返回全部笔记 →</a></div>';
    return;
  }
  const paths = data.paths.filter(p => p && Array.isArray(p.branches));
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const color = value => /^#[0-9a-f]{3,8}$/i.test(value || '') ? value : '#b8f3c6';
  const safeUrl = value => /^(?:lessons|assets)\/[a-zA-Z0-9_./-]+(?:\.html|\.webp|\.jpg|\.jpeg|\.png)$/i.test(value || '') && !value.includes('..') ? value : '';
  const lessons = branch => Array.isArray(branch.lessons) ? branch.lessons : [];
  const entries = paths.flatMap(path => path.branches.flatMap(branch => lessons(branch).map(lesson => ({path, branch, lesson}))));
  let done = new Set();
  try { const stored = JSON.parse(localStorage.getItem('search-quality-course-v1') || '[]'); if (Array.isArray(stored)) done = new Set(stored.filter(x => typeof x === 'string' && /^BV[0-9A-Za-z]{10}$/.test(x))); } catch (_) {}
  const duration = n => Number(n) > 0 ? `${Math.ceil(Number(n) / 60)} 分钟` : '时长待补充';
  const count = branch => lessons(branch).length;
  const readable = entries.filter(x => x.lesson.ready);
  const motionQuery = matchMedia('(prefers-reduced-motion: reduce)');
  const scrollBehavior = () => motionQuery.matches ? 'instant' : 'smooth';
  const hash = () => { try { return decodeURIComponent(location.hash.slice(1)).split('/'); } catch (_) { return []; } };
  const current = () => { const [p, b] = hash(); const path = paths.find(x => x.id === p); return {path, branch: path?.branches.find(x => x.id === b)}; };
  const navigate = (p, b) => { const target = p ? `#${encodeURIComponent(p)}${b ? '/' + encodeURIComponent(b) : ''}` : '#'; if (location.hash !== target && (p || location.hash)) history.pushState(null, '', target); render(); };
  const card = (item, branch) => {
    const cover = safeUrl(item.cover), href = safeUrl(item.href), starts = Array.isArray(branch.start_bvids) ? branch.start_bvids : [];
    const isStart = starts.includes(item.bvid);
    const source = /^BV[0-9A-Za-z]{10}$/.test(item.bvid || '') ? `https://www.bilibili.com/video/${item.bvid}/` : '';
    const coverContent = `<div class="cover-fallback">暂无视频封面</div>${cover ? `<img src="${esc(cover)}" alt="" loading="lazy" onerror="this.remove()">` : ''}`;
    const coverElement = item.ready && href ? `<a class="cover" href="${esc(href)}" aria-label="打开笔记：${esc(item.title || item.bvid)}">${coverContent}</a>` : `<div class="cover">${coverContent}</div>`;
    return `<article class="card" id="lesson-${esc(item.bvid)}">${coverElement}<div class="card-body"><div class="card-meta">${isStart ? '建议先读 · ' : ''}${esc(item.role || '专题补充')}　/　视频 ${duration(item.duration_seconds)}</div><h4>${item.ready && href ? `<a href="${esc(href)}">${esc(item.title)}</a>` : esc(item.title)}</h4><p>${esc(item.summary || '打开笔记，了解这一主题。')}</p><div class="card-actions">${item.ready ? `<label><input type="checkbox" data-done="${esc(item.bvid)}" ${done.has(item.bvid) ? 'checked' : ''}> 已学过</label>` : ''}${item.ready && href ? `<a href="${esc(href)}">打开笔记 ↗</a>` : `<span class="unavailable">笔记待整理</span>${!item.ready && source ? `<a href="${source}" target="_blank" rel="noopener noreferrer">观看原视频 ↗</a>` : ''}`}</div></div></article>`;
  };
  const curves = ['M 180 103 C 310 103 255 240 370 240','M 180 233 C 265 230 300 240 370 240','M 180 363 C 315 363 260 240 370 240','M 630 240 C 755 240 680 103 820 103','M 630 240 C 720 240 740 233 820 233','M 630 240 C 745 240 690 363 820 363'];
  const svg = `<svg class="map-svg" viewBox="0 0 1000 480" preserveAspectRatio="none" aria-hidden="true"><defs><linearGradient id="river" gradientUnits="userSpaceOnUse" x1="250" y1="240" x2="750" y2="240"><stop stop-color="#aad8f0"/><stop offset=".5" stop-color="#b8f3c6"/><stop offset="1" stop-color="#f1d59b"/></linearGradient></defs><path class="stream river-glow" d="M 250 240 C 390 240 610 240 750 240"/><path class="stream stream-main" d="M 250 240 C 390 240 610 240 750 240"/>${curves.map((d,i)=>`<g class="tributary" style="--stream:${color(paths[i]?.color)};--delay:-${i*2}s"><path class="stream" d="${d}"/><path class="current" d="${d}"/></g>`).join('')}<path class="current main-current" d="M 250 240 C 390 240 610 240 750 240"/></svg>`;
  const render = () => {
    const {path, branch} = current();
    const spine = Array.isArray(data.spine) ? data.spine : [];
    const next = entries.find(x => x.lesson.ready && !done.has(x.lesson.bvid) && (x.branch.start_bvids || []).includes(x.lesson.bvid)) || entries.find(x => x.lesson.ready && !done.has(x.lesson.bvid));
    const savedQuery = document.getElementById('flow-search')?.value || '';
    app.innerHTML = `<section class="hero"><div><div class="eyebrow">A MAP FOR CURIOUS MINDS / 学习脉络</div><h1>从一个问题，<br><em>找到你的路径。</em></h1><p>把散落的笔记连成可探索的脉络。先选一个方向，再沿着具体问题深入；每一步都可以按需进入。</p></div><div class="search-wrap"><label for="flow-search">带着问题来？搜索标题或概念</label><input id="flow-search" type="search" placeholder="例如：Agent、产品、学习方法" autocomplete="off"></div></section><div id="search-results" class="search-results" hidden></div><section id="overview"><div class="overview-heading"><div><div class="eyebrow">01 / THE BIG PICTURE</div><h2>先看全貌，再选择方向</h2></div><p>选择一条主线，展开其中的具体问题 ↓</p></div><div class="map">${svg}<div class="map-note">主干 / AI 与产品的三个起点</div><div class="spine">${spine.map((x,i) => `<a class="spine-item" href="${esc(safeUrl(x.href))}" title="${esc(x.description)}"><span>0${i+1}</span>${esc(x.label)}</a>`).join('')}</div>${paths.map((p,i) => `<button class="map-node" style="--accent:${color(p.color)}" data-path="${esc(p.id)}" aria-pressed="${path?.id === p.id}"><strong><span class="map-index">0${i+1}</span>${esc(p.label)}</strong><small>${p.branches.length} 个分支 · ${p.branches.flatMap(lessons).filter(l=>l.ready).length} 篇可读</small></button>`).join('')}</div><div class="under-map"><span><b>主干</b> 建立共同理解　 /　 <b>支流</b> 按兴趣深入</span><span>三篇起点贯穿 AI 与产品；其他方向可以单独进入。</span></div><p class="recommend">${next ? `不知道从哪里开始？试试 <button data-go-path="${esc(next.path.id)}" data-go-branch="${esc(next.branch.id)}">${esc(next.branch.label)} → ${esc(next.lesson.title)}</button>` : '选择感兴趣的主线，找到适合自己的下一步。'}　<span class="status">本机已学 ${readable.filter(x => done.has(x.lesson.bvid)).length} / ${readable.length} 篇</span></p></section>${!path ? `<section class="gateway"><div class="section-heading"><div><div class="eyebrow">START HERE / 主线中的主线</div><h2>从这三篇，把关键问题接起来</h2><p>先弄清概念，再理解任务，最后学会判断结果。</p></div></div><div class="gateway-cards">${spine.map((x,i)=>`<a class="gateway-card" href="${esc(safeUrl(x.href))}"><div class="gateway-cover">${safeUrl(x.cover)?`<img src="${esc(safeUrl(x.cover))}" alt="" loading="lazy">`:'' }<span>0${i+1}</span></div><div><h3>${esc(x.label)} ↗</h3><p>${esc(x.description)}</p><small>${esc(x.title)}</small></div></a>`).join('')}</div></section>` : ''}<div id="detail"></div>`;
    const detail = document.getElementById('detail');
    if (path) {
      detail.className = 'detail'; detail.style.setProperty('--accent', color(path.color));
      detail.innerHTML = `<div class="breadcrumbs"><button data-reset>全部主线</button><span> / </span><span>${esc(path.label)}</span>${branch ? `<span> / </span><span>${esc(branch.label)}</span>` : ''}</div><div class="detail-title"><div><div class="eyebrow">02 / FOLLOW A THREAD</div><h2>${esc(path.label)}</h2><p>${esc(path.description)}</p></div><button class="quiet-button" data-reset>← 返回总览</button></div><div class="section-heading"><div><h2>选择一个具体问题</h2><p>每个分支都有建议起点，也可以自由探索。</p></div></div><div class="branch-grid">${path.branches.map((b,i) => `<button class="branch" data-branch="${esc(b.id)}" aria-pressed="${branch?.id === b.id}"><small>BRANCH / ${String(i+1).padStart(2,'0')} · ${count(b)} 篇</small><strong>${esc(b.label)} ↗</strong><span>${esc(b.description)}</span></button>`).join('')}</div>${branch ? `<section class="branch-content" id="branch-content"><div class="branch-intro"><div class="eyebrow">03 / EXPLORE THE DETAILS</div><h3>${esc(branch.label)}</h3><p>${esc(branch.description)}</p><p><strong>阅读建议：</strong>${esc(branch.sequence_reason || '从感兴趣的内容开始，按需补充。')}</p></div><div class="cards">${lessons(branch).map(x => card(x, branch)).join('')}</div>${count(branch) ? '' : '<p class="status">这个分支的笔记正在整理。</p>'}</section>` : ''}`;
    }
    const search = document.getElementById('flow-search'); search.value = savedQuery;
    const showSearch = () => {
      const query = search.value.trim().toLocaleLowerCase(), box = document.getElementById('search-results');
      box.hidden = !query;
      if (!query) return;
      const matches = entries.filter(({path:p,branch:b,lesson:l}) => [p.label,b.label,l.title,l.summary,l.role,l.bvid].join(' ').toLocaleLowerCase().includes(query));
      box.innerHTML = `<div class="section-heading"><div><div class="eyebrow">SEARCH / 搜索结果</div><h2>找到 ${matches.length} 篇相关笔记</h2><p>选择结果，打开它所在的分支。</p></div></div><div class="result-list">${matches.map(({path:p,branch:b,lesson:l}) => `<button class="result" data-go-path="${esc(p.id)}" data-go-branch="${esc(b.id)}" data-go-lesson="${esc(l.bvid)}"><small>${esc(p.label)} / ${esc(b.label)}</small><strong>${esc(l.title)}</strong></button>`).join('') || '<p class="status">没有找到相关内容，换个词试试。</p>'}</div>`;
    };
    search.addEventListener('input', showSearch); showSearch();
  };
  app.addEventListener('click', e => {
    const target = e.target.closest('button'); if (!target) return;
    if (target.hasAttribute('data-reset')) { navigate(); window.scrollTo({top:0,behavior:scrollBehavior()}); }
    else if (target.dataset.path) { navigate(target.dataset.path); requestAnimationFrame(() => document.getElementById('detail')?.scrollIntoView({behavior:scrollBehavior()})); }
    else if (target.dataset.branch) { navigate(current().path.id, target.dataset.branch); requestAnimationFrame(() => document.getElementById('branch-content')?.scrollIntoView({behavior:scrollBehavior()})); }
    else if (target.dataset.goPath) { const id = target.dataset.goLesson; navigate(target.dataset.goPath, target.dataset.goBranch); requestAnimationFrame(() => { const search = document.getElementById('flow-search'); if (search) { search.value = ''; search.dispatchEvent(new Event('input')); } (id && document.getElementById(`lesson-${id}`) || document.getElementById('branch-content'))?.scrollIntoView({behavior:scrollBehavior(),block:'start'}); }); }
  });
  app.addEventListener('change', e => { if (!e.target.matches('[data-done]')) return; const id = e.target.dataset.done; e.target.checked ? done.add(id) : done.delete(id); try { localStorage.setItem('search-quality-course-v1', JSON.stringify([...done])); } catch (_) {} const input = app.querySelector(`[data-done="${id}"]`); const status = app.querySelector('.recommend .status'); if (status) status.textContent = `本机已学 ${readable.filter(x => done.has(x.lesson.bvid)).length} / ${readable.length} 篇`; input?.focus(); });
  window.addEventListener('hashchange', render);
  window.addEventListener('storage', e => { if (e.key !== 'search-quality-course-v1') return; try { const value = JSON.parse(e.newValue || '[]'); done = new Set(Array.isArray(value) ? value : []); render(); } catch (_) {} });
  const motion = document.getElementById('motion-toggle');
  motion.addEventListener('click', () => { const paused = !document.body.classList.contains('paused'); document.body.classList.toggle('paused', paused); motion.setAttribute('aria-pressed', String(paused)); motion.textContent = paused ? '恢复动效' : '暂停动效'; });
  document.addEventListener('visibilitychange', () => document.body.classList.toggle('background', document.hidden));
  render();
})();
