// 주식 AI 사이트 키트 — 공통 스크립트 (연락 버튼, 상담 신청, 종목 검색)
(function () {
  const S = window.SITE || {};
  const $ = (q, el = document) => el.querySelector(q);
  const $$ = (q, el = document) => Array.from(el.querySelectorAll(q));

  // ── 연락 버튼 ──
  $$('[data-kakao]').forEach(a => {
    if (S.kakao_url) { a.href = S.kakao_url; a.target = '_blank'; a.rel = 'noopener'; }
  });
  $$('[data-tel]').forEach(a => { if (S.phone) a.href = 'tel:' + S.phone.replace(/[^0-9+]/g, ''); });
  $$('[data-tel-text]').forEach(s => { if (S.phone) s.textContent = S.phone; });
  $$('[data-hours]').forEach(p => { p.textContent = S.phone ? '전화 상담 ' + (S.phone_hours || '') : ''; });
  $$('[data-biz]').forEach(p => { if (S.phone) p.textContent = (S.biz_info || '') + ' · 문의 ' + S.phone; });

  // ── 상담 신청 (모든 양식 공통: 본 양식, AI 박스, 메인, 팝업) ──
  const fmtPhone = v => {
    const d = v.replace(/\D/g, '').slice(0, 11);
    return d.length < 4 ? d : d.length < 8 ? d.slice(0, 3) + '-' + d.slice(3)
      : d.slice(0, 3) + '-' + d.slice(3, d.length - 4) + '-' + d.slice(-4);
  };
  const SOURCE_KR = { main: '하단 상담양식', popup: '하단 팝업' };
  const markDone = () => { try { sessionStorage.setItem('lead_done', '1'); } catch (_) {} };
  const isDone = () => { try { return sessionStorage.getItem('lead_done') === '1'; } catch (_) { return false; } };

  $$('form[data-lead]').forEach(form => {
    const err = $('.lead-error', form), btn = $('button[type=submit]', form);
    const btnText = btn.textContent;
    const done = form.parentElement.querySelector('.lead-done');
    const showErr = m => { err.textContent = m; err.hidden = false; };
    const f = n => form.elements[n];
    f('phone').addEventListener('input', e => { e.target.value = fmtPhone(e.target.value); });
    form.addEventListener('submit', async e => {
      e.preventDefault();
      err.hidden = true;
      if (f('website') && f('website').value) return;
      if (!/^01[016789]-?\d{3,4}-?\d{4}$/.test(f('phone').value)) return showErr('휴대폰 번호를 정확히 입력해 주세요.');
      if (!f('agree_privacy').checked) return showErr('개인정보 수집·이용 동의에 체크해 주세요.');
      if (!S.sheet_url) return showErr('아직 접수 연결이 설정되지 않았습니다. 카카오톡이나 전화로 문의해 주세요.');
      btn.disabled = true; btn.textContent = '접수 중...';
      const stock = document.body.dataset.stock || '';
      const body = new URLSearchParams({
        name: f('name') ? f('name').value.trim() : '',
        phone: f('phone').value,
        exp: f('exp') ? f('exp').value : '',
        msg: f('msg') ? f('msg').value.trim() : '',
        agree_privacy: 'Y',
        agree_marketing: f('agree_marketing') && f('agree_marketing').checked ? 'Y' : 'N',
        page: location.href, ref: document.referrer,
        topic: stock || (document.title.split('|')[0] || '').trim().slice(0, 60),
        source: form.dataset.hook || SOURCE_KR[form.dataset.lead] || form.dataset.lead,
        site: S.site_name || location.hostname
      });
      try {
        const r = await fetch(S.sheet_url, { method: 'POST', body });
        const j = await r.json().catch(() => ({ ok: r.ok }));
        if (!j.ok) throw new Error(j.error || 'fail');
        form.hidden = true; if (done) done.hidden = false;
        markDone();
        const sh = $('#lead-sheet'); if (sh && !sh.contains(form)) sh.hidden = true;
      } catch (_) {
        showErr('접수 중 문제가 생겼습니다. 잠시 후 다시 시도하거나 카카오톡으로 문의해 주세요.');
        btn.disabled = false; btn.textContent = btnText;
      }
    });
  });

  // ── 아래에서 올라오는 신청 창: 페이지 절반쯤 읽으면 세션당 한 번 ──
  const sheet = $('#lead-sheet');
  if (sheet) {
    let shown = false;
    const seen = () => { try { return sessionStorage.getItem('sheet_seen') === '1'; } catch (_) { return false; } };
    const onScroll = () => {
      if (shown || seen() || isDone()) return;
      const h = document.documentElement;
      const ratio = (h.scrollTop + innerHeight) / h.scrollHeight;
      const apply = $('#apply');
      const nearForm = apply && apply.getBoundingClientRect().top < innerHeight;
      if (ratio > 0.45 && !nearForm) {
        shown = true; sheet.hidden = false;
        try { sessionStorage.setItem('sheet_seen', '1'); } catch (_) {}
      }
    };
    addEventListener('scroll', onScroll, { passive: true });
    $$('[data-close-sheet]', sheet).forEach(b => b.addEventListener('click', () => { sheet.hidden = true; }));
    addEventListener('keydown', e => { if (e.key === 'Escape') sheet.hidden = true; });
  }

  // ── 종목 검색 (상단·메인 검색창 모두) ──
  let data = null;
  const load = () => data ? Promise.resolve(data)
    : fetch((S.base || '') + '/stocks.json').then(r => r.json()).then(d => (data = d));
  const esc = s => s.replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  $$('[data-search]').forEach(sf => {
    const input = $('input', sf), list = $('.search-list', sf);
    let idx = -1;
    const render = q => {
      q = q.trim().toLowerCase();
      if (!q) { list.hidden = true; return; }
      const hits = data.filter(([c, n]) => n.toLowerCase().includes(q) || c.startsWith(q))
        .sort((a, b) => (a[1].toLowerCase().startsWith(q) ? 0 : 1) - (b[1].toLowerCase().startsWith(q) ? 0 : 1))
        .slice(0, 12);
      idx = -1;
      list.innerHTML = hits.length
        ? hits.map(([c, n, m]) => `<li><a href="${S.base || ''}/stock/${c}/"><span>${esc(n)}</span><span class="c">${c} · ${m === 'KOSPI' ? '코스피' : '코스닥'}</span></a></li>`).join('')
        : '<li><a href="#" aria-disabled="true"><span>검색 결과가 없습니다</span></a></li>';
      list.hidden = false;
    };
    input.addEventListener('focus', load, { once: true });
    input.addEventListener('input', () => load().then(() => render(input.value)));
    input.addEventListener('keydown', e => {
      const links = $$('a', list);
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        idx = Math.max(0, Math.min(links.length - 1, idx + (e.key === 'ArrowDown' ? 1 : -1)));
        links.forEach((a, i) => a.classList.toggle('on', i === idx));
      }
    });
    sf.addEventListener('submit', e => {
      e.preventDefault();
      load().then(() => {
        if (list.hidden) render(input.value);
        const links = $$('a', list).filter(a => !a.getAttribute('aria-disabled'));
        const a = links[Math.max(0, idx)];
        if (a) location.href = a.href;
      });
    });
    document.addEventListener('click', e => { if (!sf.contains(e.target)) list.hidden = true; });
  });

  // ── 후킹 버튼 → 전화번호 입력 창 ──
  const modal = $('#hook-modal');
  if (modal) {
    const mform = $('form', modal), mdone = $('.lead-done', modal);
    let lastFocus = null;
    const close = () => { modal.hidden = true; document.body.classList.remove('no-scroll'); if (lastFocus) lastFocus.focus(); };
    $$('[data-hook]').forEach(b => b.addEventListener('click', () => {
      lastFocus = b;
      mform.dataset.hook = b.dataset.hook;
      $('#hook-tag').textContent = b.dataset.hook + ' · 무료';
      $('#hook-title').textContent = b.dataset.hookTitle || b.dataset.hook;
      $('#hook-sub').textContent = b.dataset.hookSub || '';
      if (!mdone.hidden) { mform.hidden = false; mdone.hidden = true; mform.reset();
        const btn = $('button[type=submit]', mform); btn.disabled = false; btn.textContent = '무료 신청'; }
      $('.lead-error', mform).hidden = true;
      modal.hidden = false; document.body.classList.add('no-scroll');
      const sh = $('#lead-sheet'); if (sh) sh.hidden = true;
      setTimeout(() => mform.elements.phone.focus(), 30);
    }));
    $$('[data-close-modal]', modal).forEach(x => x.addEventListener('click', close));
    addEventListener('keydown', e => { if (e.key === 'Escape' && !modal.hidden) close(); });
  }

  // ── 메인: 종목 입력 → 그 자리에서 AI 기본 예측 표시 ──
  const tool = $('[data-tool]');
  if (tool) {
    const input = $('input', tool), list = $('.search-list', tool), box = $('#tool-result');
    const R = k => $(`[data-r="${k}"]`, box);
    const won = v => Math.round(v).toLocaleString('ko-KR');
    const pctTxt = v => (v > 0 ? '+' : '') + v.toFixed(2) + '%';
    const cls = v => v > 0 ? 'up' : v < 0 ? 'down' : '';
    let hits = [];
    const show = row => {
      const [c, n, m, close, chg, p, lo, hi] = row;
      R('name').textContent = n; R('code').textContent = c;
      R('close').textContent = won(close);
      R('chg').textContent = pctTxt(chg); R('chg').className = cls(chg);
      const sc = p == null ? '' : p >= 0.55 ? 'up' : p <= 0.45 ? 'down' : 'flat';
      R('p').textContent = p == null ? '-' : Math.round(p * 100);
      R('pbox').className = 'ai-p ' + sc;
      R('signal').textContent = p == null ? '데이터 부족' : p >= 0.55 ? '상승 우위' : p <= 0.45 ? '하락 우위' : '중립';
      R('signal').className = 'ai-signal ' + sc;
      R('meter').style.width = Math.round((p == null ? 0.5 : p) * 100) + '%';
      R('lo').textContent = won(lo); R('hi').textContent = won(hi);
      R('link').href = (S.base || '') + '/stock/' + c + '/';
      document.body.dataset.stock = n + ' (' + c + ')';
      $$('[data-hook]').forEach(b => {
        const base = b.dataset.hook;
        b.dataset.hookTitle = n + ' ' + base + ' 무료 신청';
      });
      list.hidden = true; input.value = n;
      box.classList.remove('flash'); void box.offsetWidth; box.classList.add('flash');
    };
    const render = q => {
      q = q.trim().toLowerCase();
      if (!q) { list.hidden = true; hits = []; return; }
      hits = data.filter(([c, n]) => n.toLowerCase().includes(q) || c.startsWith(q))
        .sort((a, b) => (a[1].toLowerCase().startsWith(q) ? 0 : 1) - (b[1].toLowerCase().startsWith(q) ? 0 : 1))
        .slice(0, 10);
      list.innerHTML = hits.length
        ? hits.map((h, i) => `<li><button type="button" data-i="${i}"><span>${esc(h[1])}</span><span class="c">${h[0]} · ${h[2] === 'KOSPI' ? '코스피' : '코스닥'}</span></button></li>`).join('')
        : '<li><span class="none">검색 결과가 없습니다</span></li>';
      list.hidden = false;
    };
    input.addEventListener('focus', load, { once: true });
    input.addEventListener('input', () => load().then(() => render(input.value)));
    list.addEventListener('click', e => { const b = e.target.closest('button[data-i]'); if (b) show(hits[+b.dataset.i]); });
    tool.addEventListener('submit', e => {
      e.preventDefault();
      load().then(() => { if (!hits.length) render(input.value); if (hits[0]) show(hits[0]); });
    });
    document.addEventListener('click', e => { if (!tool.contains(e.target)) list.hidden = true; });
  }
})();
