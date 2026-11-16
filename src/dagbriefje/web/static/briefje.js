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

  function eventList(events, emptyText) {
    if (!events.length) return el('p', 'quiet', emptyText);
    const list = el('ul', 'events');
    for (const event of events) {
      const item = el('li');
      item.append(el('span', 'when', event.all_day ? 'hele dag' : event.start + ' – ' + event.end));
      const what = el('span', 'what');
      what.append(el('span', '', event.title));
      if (event.location) what.append(el('span', 'where', event.location));
      item.append(what);
      list.append(item);
    }
    return list;
  }

  const panels = {
    agenda(data) {
      title.textContent = 'Agenda';
      const today = el('section');
      today.append(el('span', 'label', 'Vandaag'), eventList(data.today, 'Niets gepland.'));
      const tomorrow = el('section');
      tomorrow.append(el('span', 'label', 'Morgen'), eventList(data.tomorrow, 'Niets gepland.'));
      body.replaceChildren(today, tomorrow);
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
