// Settings page: notifications on this phone, and the code for the home-screen widget.
(function () {
  async function post(url, data) {
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify(data || {}),
    });
    return response.ok ? response.json() : Promise.reject(new Error(String(response.status)));
  }

  // --- notifications ---------------------------------------------------------
  const box = document.getElementById('push');
  if (box && box.dataset.key) {
    const status = box.querySelector('[data-status]');
    const on = box.querySelector('[data-on]');
    const off = box.querySelector('[data-off]');
    const test = box.querySelector('[data-test]');
    const say = (text) => { status.textContent = text; };
    const supported = 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
    const standalone = window.matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
    const ios = /iPhone|iPad|iPod/.test(navigator.userAgent);

    function keyBytes(text) {
      const base64 = (text + '='.repeat((4 - (text.length % 4)) % 4)).replace(/-/g, '+').replace(/_/g, '/');
      return Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
    }

    async function registration() {
      await navigator.serviceWorker.register('/sw.js');
      return navigator.serviceWorker.ready;
    }

    function show(subscribed) {
      on.hidden = subscribed;
      off.hidden = !subscribed;
      test.hidden = !subscribed;
    }

    async function refresh() {
      if (!supported) {
        say(ios && !standalone
          ? 'Zet het briefje eerst op je beginscherm: tik op Deel en dan "Zet op beginscherm". Open het daarna van daaruit en kom hier terug.'
          : 'Deze browser kan geen meldingen tonen.');
        on.hidden = off.hidden = test.hidden = true;
        return;
      }
      const reg = await registration();
      const sub = await reg.pushManager.getSubscription();
      show(Boolean(sub));
      say(sub ? 'Meldingen staan aan op dit toestel.' : 'Meldingen staan uit op dit toestel.');
    }

    on.addEventListener('click', async () => {
      try {
        const permission = await Notification.requestPermission();
        if (permission !== 'granted') {
          say('Je gaf geen toestemming. Dat pas je aan in de instellingen van je gsm, bij Meldingen.');
          return;
        }
        const reg = await registration();
        const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(box.dataset.key) });
        await post('/meldingen/abonneer', sub.toJSON());
        show(true);
        say('Meldingen staan aan op dit toestel. Stuur een test om te kijken of ze aankomen.');
      } catch (error) {
        say('Aanzetten lukte niet (' + error.message + ').');
      }
    });

    off.addEventListener('click', async () => {
      const reg = await registration();
      const sub = await reg.pushManager.getSubscription();
      if (sub) {
        await post('/meldingen/uitschrijven', { endpoint: sub.endpoint }).catch(() => {});
        await sub.unsubscribe();
      }
      show(false);
      say('Meldingen staan uit op dit toestel.');
    });

    test.addEventListener('click', async () => {
      say('Testmelding wordt verstuurd…');
      try {
        const result = await post('/meldingen/test');
        say(result.sent ? 'Verstuurd. Hij zou binnen enkele seconden moeten verschijnen.' : 'Niet verstuurd: ' + (result.error || 'onbekende fout') + '.');
      } catch (error) {
        say('Niet verstuurd (' + error.message + ').');
      }
    });

    refresh();
  }

  // --- widget ----------------------------------------------------------------
  const code = document.getElementById('widget-code');
  const copy = document.getElementById('widget-copy');
  if (code && copy) {
    fetch('/static/widget-scriptable.js')
      .then((r) => r.text())
      .then((text) => { code.value = text.replace('__DAILYLETTER_URL__', window.location.origin); });
    copy.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(code.value);
        copy.textContent = 'Gekopieerd';
      } catch (error) {
        code.select();
        copy.textContent = 'Selecteer en kopieer zelf';
      }
    });
  }
})();
