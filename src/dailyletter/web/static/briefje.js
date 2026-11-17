// Detail panels are filled from facts that the batch job stored with the briefing.
(function () {
  const details = JSON.parse(document.getElementById('details').textContent || '{}');
  const sheet = document.getElementById('sheet');
  const title = document.getElementById('sheet-title');
  const body = document.getElementById('sheet-body');
  let opener = null;

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function eventList(events, emptyText, showCalendar) {
    if (!events.length) return el('p', 'quiet', emptyText);
    const list = el('ul', 'events');
    for (const event of events) {
      const item = el('li');
      item.append(el('span', 'when', event.all_day ? 'hele dag' : event.start + ' – ' + event.end));
      const what = el('span', 'what');
      what.append(el('span', '', event.title));
      const where = [showCalendar ? event.calendar : null, event.location].filter(Boolean).join(' · ');
      if (where) what.append(el('span', 'where', where));
      item.append(what);
      list.append(item);
    }
    return list;
  }

  function newsList(items, feedLabel) {
    const list = el('ul', 'news');
    for (const item of items) {
      const row = el('li');
      // Only real web links; anything else stays plain text.
      const safe = item.link && /^https?:\/\//i.test(item.link);
      const head = el(safe ? 'a' : 'span', 'news-title', item.title);
      if (safe) {
        head.href = item.link;
        head.target = '_blank';
        head.rel = 'noopener noreferrer';
      }
      const source = item.source === feedLabel ? '' : item.source;
      row.append(head, el('span', 'where', [source, item.when].filter(Boolean).join(' · ')));
      if (item.summary) row.append(el('span', 'news-summary', item.summary));
      list.append(row);
    }
    return list;
  }

  const panels = {
    news(data) {
      title.textContent = 'Nieuws';
      const parts = [];
      for (const p of data.positions) {
        const box = el('section');
        box.append(el('span', 'label', p.name + (p.move ? ' · ' + p.move : '')), newsList(p.items));
        parts.push(box);
      }
      for (const feed of data.general) {
        const box = el('section');
        box.append(el('span', 'label', feed.label), newsList(feed.items, feed.label));
        parts.push(box);
      }
      if (data.failed) parts.push(el('p', 'quiet small', data.failed));
      parts.push(el('p', 'quiet small', data.note));
      body.replaceChildren(...parts);
    },

    agenda(data) {
      title.textContent = 'Agenda';
      // Name the calendar only when there is more than one; with one it is noise.
      const names = new Set(data.today.concat(data.tomorrow).map((e) => e.calendar).filter(Boolean));
      const showCalendar = names.size > 1;
      const today = el('section');
      today.append(el('span', 'label', 'Vandaag'), eventList(data.today, 'Niets gepland.', showCalendar));
      const tomorrow = el('section');
      tomorrow.append(el('span', 'label', 'Morgen'), eventList(data.tomorrow, 'Niets gepland.', showCalendar));
      body.replaceChildren(today, tomorrow);
    },

    sport(data) {
      title.textContent = 'Training';
      const parts = [];

      const head = el('section');
      head.append(el('span', 'label', data.label), el('h2', '', data.headline));
      parts.push(head);

      if (data.tiles.length) {
        const tiles = el('div', 'tiles');
        for (const tile of data.tiles) {
          const box = el('div', 'tile');
          box.append(el('span', 'tile-k', tile.k), el('span', 'tile-v', tile.v));
          if (tile.s) box.append(el('span', 'tile-s', tile.s));
          tiles.append(box);
        }
        parts.push(tiles);
      }

      if (data.reasons.length) {
        const why = el('section');
        const list = el('ul', 'reasons');
        for (const reason of data.reasons) list.append(el('li', '', reason));
        why.append(el('span', 'label', 'Waarom'), list);
        parts.push(why);
      }

      const week = el('section');
      const strip = el('div', 'week');
      for (const day of data.week) {
        const cell = el('div', 'day' + (day.today ? ' today' : '') + (day.items.length ? ' active' : ''));
        cell.append(el('span', 'day-name', day.day), el('span', 'dot'));
        const empty = day.today ? 'vandaag' : 'rust';
        cell.append(el('span', 'day-items', day.items.length ? day.items.join(' + ') : empty));
        strip.append(cell);
      }
      week.append(
        el('span', 'label', 'Deze week'),
        strip,
        el('p', 'quiet small', 'Gelopen: ' + data.run_km_week + ' km. Gemiddeld per week: ' + data.run_km_avg + ' km.'
          + (data.run_km_target ? ' Doel uit je plan: ' + data.run_km_target + ' km.' : '')),
      );
      parts.push(week);

      parts.push(el('p', 'quiet small', data.note));
      body.replaceChildren(...parts);
    },

    portfolio(data) {
      title.textContent = 'Portefeuille';
      const parts = [];
      const amounts = [];
      // Amounts stay hidden until asked: a glance at your letter should not turn into watching money.
      function amount(text, className) {
        const span = el('span', 'amount ' + (className || ''), '••••');
        span.dataset.value = text || '–';
        amounts.push(span);
        return span;
      }

      if (data.total) {
        const head = el('section');
        const row = el('div', 'total-row');
        const eye = el('button', 'icon');
        eye.type = 'button';
        eye.setAttribute('aria-label', 'Toon bedragen');
        eye.setAttribute('aria-pressed', 'false');
        eye.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>';
        eye.addEventListener('click', () => {
          const show = eye.getAttribute('aria-pressed') !== 'true';
          eye.setAttribute('aria-pressed', String(show));
          eye.setAttribute('aria-label', show ? 'Verberg bedragen' : 'Toon bedragen');
          for (const span of amounts) span.textContent = show ? span.dataset.value : '••••';
        });
        row.append(amount(data.total, 'total'), eye);
        head.append(el('span', 'label', data.fresh ? 'Waarde' : 'Waarde, niet ververst'), row);
        parts.push(head);
      }

      if (data.returns.length) {
        const tiles = el('div', 'tiles');
        for (const r of data.returns) {
          const box = el('div', 'tile');
          box.append(el('span', 'tile-k', r.k), el('span', 'tile-v', r.v));
          tiles.append(box);
        }
        parts.push(tiles);
      }

      if (data.insights.length) {
        const box = el('section');
        const list = el('ul', 'reasons');
        for (const line of data.insights) list.append(el('li', '', line));
        box.append(el('span', 'label', 'Valt op'), list);
        parts.push(box);
      }

      if (data.positions.length) {
        const box = el('section');
        const list = el('ul', 'holdings');
        for (const p of data.positions) {
          const item = el('li');
          const left = el('span', 'what');
          left.append(el('span', '', p.name));
          left.append(el('span', 'where', [p.symbol, p.weight].filter(Boolean).join(' · ')));
          const right = el('span', 'move');
          right.append(el('span', '', p.day || ''));
          if (p.pl) right.append(el('span', 'where', 'sinds aankoop ' + p.pl));
          right.append(amount(p.value, 'where'));
          item.append(left, right);
          list.append(item);
        }
        box.append(el('span', 'label', 'Posities'), list);
        parts.push(box);
      }

      if (data.cash || data.orders !== null) {
        const foot = el('p', 'small');
        foot.append('Cash: ');
        foot.append(amount(data.cash));
        if (data.orders !== null) foot.append(' · open orders: ' + data.orders);
        parts.push(foot);
      }

      parts.push(el('p', 'quiet small', data.note));
      body.replaceChildren(...parts);
    },
  };

  function open(name, from) {
    if (!panels[name] || !details[name]) return;
    panels[name](details[name]);
    opener = from;
    sheet.hidden = false;
    sheet.querySelector('.icon').focus();
  }

  function close() {
    sheet.hidden = true;
    if (opener) opener.focus();
  }

  document.querySelectorAll('[data-detail]').forEach((button) => {
    button.addEventListener('click', () => open(button.dataset.detail, button));
  });
  sheet.querySelectorAll('[data-close]').forEach((button) => button.addEventListener('click', close));
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !sheet.hidden) close();
  });
})();
