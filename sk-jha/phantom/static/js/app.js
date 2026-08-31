import { api } from './api.js';
import { clear, el, toast } from './ui.js';
import { renderDashboard } from './views/dashboard.js';
import { renderConsole } from './views/console.js';
import { renderSetup } from './views/setup.js';
import { renderColumns } from './views/columns.js';

const view = document.getElementById('view');
let teardown = null;

const ROUTES = [
  [/^\/?$/, () => renderDashboard(view)],
  [/^\/columns$/, () => renderColumns(view)],
  [/^\/agents\/(\d+)\/setup$/, (id) => renderSetup(view, Number(id))],
  [/^\/agents\/(\d+)$/, (id) => renderConsole(view, Number(id))],
];

async function route() {
  const path = window.location.hash.replace(/^#/, '') || '/';

  if (teardown) {
    try {
      teardown();
    } catch {

    }
    teardown = null;
  }

  for (const [pattern, handler] of ROUTES) {
    const match = path.match(pattern);
    if (!match) continue;
    try {
      teardown = (await handler(...match.slice(1))) || null;
    } catch (error) {
      clear(view).append(
        el(
          'div',
          { class: 'card' },
          el('h2', {}, 'Could not load this page'),
          el('p', { class: 'mono muted' }, error.message),
          el('a', { class: 'btn', href: '#/' }, 'Back to dashboard'),
        ),
      );
      toast(error.message, 'err');
    }
    markActiveNav(path);
    return;
  }

  clear(view).append(
    el('div', { class: 'card empty-state' }, `No route matches ${path}`),
  );
}

function markActiveNav(path) {
  for (const link of document.querySelectorAll('.topnav a[data-link]')) {
    const target = link.getAttribute('href').replace(/^#/, '');
    link.classList.toggle('active', target === path || (target === '/' && path === '/'));
  }
}

async function refreshQuota() {
  try {
    const quota = await api.quota();
    document.getElementById('quota').textContent =
      `${quota.used} / ${quota.cap} profiles today`;
  } catch {
    document.getElementById('quota').textContent = '';
  }
}

window.addEventListener('hashchange', route);

route();
refreshQuota();
setInterval(refreshQuota, 15000);
