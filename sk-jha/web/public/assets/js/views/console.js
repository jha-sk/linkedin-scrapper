import { api } from '../api.js';
import { clear, clockTime, el, initials, progressBar, statusTag, timeAgo, toast } from '../ui.js';

const PER_PAGE_OPTIONS = [5, 10, 20, 30];

export async function renderConsole(view, agentId) {
  clear(view);

  let agent = await api.agent(agentId);
  let columns = await api.columns();

  const state = {
    tab: 'results',
    page: 1,
    perPage: 10,
    launch: agent.last_launch,
    logs: [],
  };

  const header = el('div', {});
  const panel = el('div', {});
  const tabsBar = el('div', { class: 'tabs' });
  view.append(header, tabsBar, panel);

  function paintHeader() {
    clear(header);
    const running = state.launch && ['queued', 'running'].includes(state.launch.status);

    header.append(
      el(
        'a',
        { href: '#/', class: 'muted small', style: 'display:inline-block;margin-bottom:16px' },
        '← Back to dashboard',
      ),
      el(
        'div',
        { class: 'card stack' },
        el(
          'div',
          { class: 'row' },
          el('div', { class: 'agent-avatar' }, initials(agent.name)),
          el(
            'div',
            {},
            el('div', { class: 'muted small' }, agent.kind),
            el('h1', { style: 'margin:0' }, agent.name),
          ),
          el('div', { class: 'spacer' }),
          el(
            'a',
            { class: 'btn btn-sm', href: `#/agents/${agent.id}/setup` },
            'Configure',
          ),
          running
            ? el(
                'button',
                { class: 'btn btn-danger', onClick: () => cancel() },
                'Cancel run',
              )
            : el(
                'button',
                {
                  class: 'btn btn-primary',
                  disabled: !agent.is_configured,
                  onClick: () => launch(),
                },
                'Launch',
              ),
        ),
        el(
          'div',
          { class: 'row' },
          statusTag(state.launch ? state.launch.status : null),
          el('div', { class: 'spacer' }, progressBar(state.launch ? state.launch.progress : 0, !running)),
          el(
            'span',
            { class: 'muted small mono' },
            state.launch
              ? `${state.launch.processed}/${state.launch.targets_total || '?'} · `
                + `${state.launch.succeeded} ok · ${state.launch.failed} failed`
              : 'no runs yet',
          ),
        ),
        !agent.is_configured
          ? el('div', { class: 'notice notice-warn' },
              'This agent has no input configured. Open Configure and give it a profile URL.')
          : null,
        !agent.session_connected
          ? el('div', { class: 'notice notice-warn' },
              'No signed-in browser profile. Run `python -m phantom.session login` once — the '
              + 'logged-out view is usually authwalled and cannot fill most columns.')
          : null,
        state.launch && state.launch.error
          ? el('div', { class: 'notice notice-err mono' }, state.launch.error)
          : null,
      ),
    );
  }

  function paintTabs() {
    clear(tabsBar);
    for (const [key, label] of [
      ['results', 'Results'],
      ['leads', 'Leads'],
      ['activity', 'Activity'],
    ]) {
      tabsBar.append(
        el(
          'button',
          {
            class: state.tab === key ? 'active' : '',
            onClick: () => {
              state.tab = key;
              state.page = 1;
              paintTabs();
              paintPanel();
            },
          },
          label,
        ),
      );
    }
  }

  async function paintPanel() {
    clear(panel);
    if (state.tab === 'activity') return paintActivity(panel, agent, state);
    const scope = state.tab;
    const data =
      scope === 'results'
        ? await api.results(agent.id, { page: state.page, perPage: state.perPage })
        : await api.leads(agent.id, { page: state.page, perPage: state.perPage });

    panel.append(
      el(
        'div',
        { class: 'row-between', style: 'margin-bottom:12px' },
        el('h2', { style: 'margin:0' }, `${scope === 'results' ? 'Results' : 'Leads'} (${data.total})`),
        el(
          'div',
          { class: 'row' },
          el(
            'a',
            { class: 'btn btn-sm', href: `/api/agents/${agent.id}/export.csv?scope=${scope}` },
            'Download CSV',
          ),
          el(
            'a',
            { class: 'btn btn-sm', href: `/api/agents/${agent.id}/export.json?scope=${scope}` },
            'JSON',
          ),
        ),
      ),
    );

    if (!data.total) {
      panel.append(
        el(
          'div',
          { class: 'card empty-state' },
          scope === 'results'
            ? 'No results yet. Launch the agent to produce some.'
            : 'No leads yet. Leads are the deduplicated people behind your result rows.',
        ),
      );
      return;
    }

    panel.append(resultTable(data.items, columns, scope), pager(data, state, paintPanel));
  }

  function resultTable(items, cols, scope) {
    const head = el(
      'thead',
      {},
      el('tr', {}, cols.map((column) => el('th', { title: column.key }, column.label))),
    );
    const body = el(
      'tbody',
      {},
      items.map((item) => {
        const payload = item.payload || {};
        return el(
          'tr',
          {},
          cols.map((column) => cell(payload[column.key], column)),
        );
      }),
    );
    return el('div', { class: 'table-wrap' }, el('table', {}, head, body));
  }

  function cell(value, column) {
    if (value === null || value === undefined || value === '') {
      return el('td', { class: 'muted' }, '—');
    }
    if (column.kind === 'bool') {
      return el('td', {}, value ? 'true' : 'false');
    }
    if (column.kind === 'url') {
      return el(
        'td',
        {},
        el('a', { href: String(value), target: '_blank', rel: 'noreferrer' }, shorten(String(value))),
      );
    }
    if (column.kind === 'int') {
      return el('td', { class: 'mono' }, String(value));
    }
    return el('td', {}, el('div', { class: 'clamp' }, String(value)));
  }

  function shorten(url) {
    return url.length > 48 ? `${url.slice(0, 45)}…` : url;
  }

  function pager(data, pageState, repaint) {
    const pages = Math.max(1, Math.ceil(data.total / data.per_page));
    return el(
      'div',
      { class: 'pager' },
      el(
        'button',
        {
          class: 'btn btn-sm',
          disabled: pageState.page <= 1,
          onClick: () => {
            pageState.page -= 1;
            repaint();
          },
        },
        'Previous',
      ),
      el('span', { class: 'muted small' }, `Page ${data.page} of ${pages} · ${data.total} entries`),
      el(
        'button',
        {
          class: 'btn btn-sm',
          disabled: pageState.page >= pages,
          onClick: () => {
            pageState.page += 1;
            repaint();
          },
        },
        'Next',
      ),
      el('div', { class: 'spacer' }),
      el('span', { class: 'muted small' }, 'Rows per page'),
      el(
        'select',
        {
          style: 'width:auto',
          onChange: (event) => {
            pageState.perPage = Number(event.target.value);
            pageState.page = 1;
            repaint();
          },
        },
        PER_PAGE_OPTIONS.map((size) =>
          el('option', { value: size, selected: size === pageState.perPage }, String(size)),
        ),
      ),
    );
  }

  async function launch() {
    try {
      state.launch = await api.launch(agent.id);
      state.logs = [];
      toast(`Launch #${state.launch.id} queued`, 'ok');
      paintHeader();
      if (state.tab === 'activity') paintPanel();
    } catch (error) {
      toast(error.message, 'err');
    }
  }

  async function cancel() {
    try {
      state.launch = await api.cancelLaunch(state.launch.id);
      toast('Cancellation requested — the run stops after the current profile.');
      paintHeader();
    } catch (error) {
      toast(error.message, 'err');
    }
  }

  const stream = new EventSource(`/api/agents/${agent.id}/stream`);
  stream.addEventListener('launch', (event) => {
    const next = JSON.parse(event.data);
    const changedRun = !state.launch || state.launch.id !== next.id;
    const becameTerminal =
      state.launch && state.launch.status !== next.status
      && ['finished', 'failed', 'cancelled'].includes(next.status);
    if (changedRun) state.logs = [];
    state.launch = next;
    paintHeader();
    if (state.tab === 'activity') renderLogs();
    if (becameTerminal) {
      api.agent(agent.id).then((fresh) => {
        agent = fresh;
        if (state.tab !== 'activity') paintPanel();
      });
    }
  });
  stream.addEventListener('log', (event) => {
    state.logs.push(JSON.parse(event.data));
    if (state.tab === 'activity') renderLogs();
  });

  function renderLogs() {
    const box = panel.querySelector('.console');
    if (!box) return;
    const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
    clear(box);
    if (!state.logs.length) {
      box.append(el('div', { class: 'empty' }, 'Waiting for output…'));
      return;
    }
    for (const line of state.logs) {
      box.append(
        el(
          'div',
          { class: `lvl-${line.level}` },
          el('span', { class: 'ts' }, clockTime(line.at)),
          line.message,
        ),
      );
    }
    if (atBottom) box.scrollTop = box.scrollHeight;
  }

  async function paintActivity(host, currentAgent, activityState) {
    const [launches, backlog] = await Promise.all([
      api.launches(currentAgent.id),
      activityState.launch ? api.logs(activityState.launch.id) : Promise.resolve([]),
    ]);
    if (backlog.length && !activityState.logs.length) activityState.logs = backlog;

    host.append(
      el('h2', {}, 'Console output'),
      el('div', { class: 'console' }),
      el('h2', { style: 'margin-top:24px' }, 'Launch history'),
      launches.length
        ? el(
            'div',
            { class: 'table-wrap' },
            el(
              'table',
              { style: 'width:100%' },
              el(
                'thead',
                {},
                el(
                  'tr',
                  {},
                  ['Launch', 'Status', 'Trigger', 'Queued', 'Duration', 'Processed', 'Failed'].map(
                    (label) => el('th', {}, label),
                  ),
                ),
              ),
              el(
                'tbody',
                {},
                launches.map((item) =>
                  el(
                    'tr',
                    {},
                    el('td', { class: 'mono' }, `#${item.id}`),
                    el('td', {}, statusTag(item.status)),
                    el('td', { class: 'muted' }, item.trigger),
                    el('td', { class: 'muted' }, timeAgo(item.queued_at)),
                    el('td', { class: 'mono' }, duration(item)),
                    el('td', { class: 'mono' }, `${item.processed}/${item.targets_total}`),
                    el('td', { class: 'mono' }, String(item.failed)),
                  ),
                ),
              ),
            ),
          )
        : el('div', { class: 'card empty-state' }, 'No launches recorded.'),
    );
    renderLogs();
  }

  function duration(launch) {
    if (!launch.started_at) return '—';
    const end = launch.finished_at ? new Date(launch.finished_at) : new Date();
    const seconds = Math.round((end - new Date(launch.started_at)) / 1000);
    if (seconds < 60) return `${seconds}s`;
    return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
  }

  paintHeader();
  paintTabs();
  await paintPanel();

  return () => stream.close();
}
