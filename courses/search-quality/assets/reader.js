(() => {
  'use strict';
  const key = 'search-quality-course-v1';
  let done = new Set();
  try { const value = JSON.parse(localStorage.getItem(key) || '[]'); if (Array.isArray(value)) done = new Set(value.filter(x => /^BV[0-9A-Za-z]{10}$/.test(x))); } catch (_) {}
  const save = () => { try { localStorage.setItem(key, JSON.stringify([...done])); } catch (_) { const msg = document.getElementById('transfer-message'); if (msg) msg.textContent = '浏览器未允许保存进度；可用导出按钮保留本次记录。'; } };
  const refresh = () => {
    document.querySelectorAll('[data-check]').forEach(x => { x.checked = done.has(x.dataset.check); });
    document.querySelectorAll('[data-done]').forEach(x => { const yes = done.has(x.dataset.done); x.textContent = yes ? '已学过 · 点击撤销' : '标记学过'; x.setAttribute('aria-pressed', String(yes)); });
    const query = (document.getElementById('course-search')?.value || '').trim().toLocaleLowerCase();
    const scope = document.getElementById('priority')?.value || 'all';
    let count = 0;
    document.querySelectorAll('.lesson-card').forEach(card => {
      const read = done.has(card.dataset.id);
      card.classList.toggle('is-done', read);
      card.hidden = !card.dataset.search.toLocaleLowerCase().includes(query) || (scope === 'unread' ? read : scope !== 'all' && scope !== card.dataset.priority);
      if (!card.hidden) count++;
    });
    document.querySelectorAll('.module').forEach(x => { x.hidden = !x.querySelector('.lesson-card:not([hidden])'); });
    const p = document.querySelector('.tools #progress');
    if (p) { const ids = [...document.querySelectorAll('[data-check]')].map(x => x.dataset.check); p.textContent = `已学 ${ids.filter(id => done.has(id)).length} / ${ids.length} 篇 · 当前显示 ${count} 篇`; }
    const empty = document.getElementById('empty'); if (empty) empty.hidden = count !== 0;
  };
  document.querySelectorAll('[data-check],[data-done]').forEach(x => x.addEventListener(x.dataset.check ? 'change' : 'click', () => { const id = x.dataset.check || x.dataset.done; done.has(id) ? done.delete(id) : done.add(id); save(); refresh(); }));
  ['course-search', 'priority'].forEach(id => document.getElementById(id)?.addEventListener('input', refresh));
  document.getElementById('export-progress')?.addEventListener('click', () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify({course:'search-quality',version:1,done:[...done]}, null, 2)], {type:'application/json'}));
    const a = document.createElement('a'); a.href = url; a.download = 'search-quality-progress.json'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  document.getElementById('import-progress')?.addEventListener('change', async e => {
    const file = e.target.files[0], msg = document.getElementById('transfer-message');
    if (!file) return;
    try {
      if (file.size > 100000) throw Error('文件过大');
      const value = JSON.parse(await file.text());
      if (value.course !== 'search-quality' || value.version !== 1 || !Array.isArray(value.done) || value.done.some(x => typeof x !== 'string' || !/^BV[0-9A-Za-z]{10}$/.test(x))) throw Error('格式不符');
      value.done.forEach(id => done.add(id)); save(); refresh(); msg.textContent = '进度已合并到当前设备，原有记录保留。';
    } catch (_) { msg.textContent = '无法导入：请选择本课程导出的进度 JSON。'; }
    e.target.value = '';
  });
  window.addEventListener('storage', () => { try { const v = JSON.parse(localStorage.getItem(key) || '[]'); if (Array.isArray(v)) done = new Set(v.filter(x => typeof x === 'string' && /^BV[0-9A-Za-z]{10}$/.test(x))); } catch (_) {} refresh(); });
  refresh();
})();
