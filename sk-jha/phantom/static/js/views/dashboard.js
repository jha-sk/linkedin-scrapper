import { api } from '../api.js';
import { clear, el, initials, statusTag, timeAgo, toast } from '../ui.js';

export async function renderDashboard(view) {
  clear(view);
  const agents = await api.agents();

  view.append(
    el(
      'div',
      { class: 'row-between', style: 'margin-bottom:22px' },
      el(
        'div',
        {},
        el('h1', {}, 'Agents'),
        el('p', { class: 'muted', style: 'margin:0' },
           'Each agent is one saved configuration plus the results every launch of it produced.'),
      ),
      el('button', { class: 'btn btn-primary', onClick: () => createAgent() }, 'New agent'),
    ),
  );

  if (!agents.length) {
    view.append(
      el(
        'div',
        { class: 'card empty-state' },
        el('p', {}, 'No agents yet.'),
        el('p', { class: 'small' },
           'An agent needs a profile URL and a LinkedIn session cookie before it can run.'),
        el('button', { class: 'btn btn-primary', onClick: () => createAgent() }, 'Create the first one'),
      ),
    );
    return;
  }

  const grid = el('div', { class: 'agent-grid' });
  for (const agent of agents) grid.append(agentCard(agent));
  view.append(grid);
}

function agentCard(agent) {
  const last = agent.last_launch;
  return el(
    'a',
    { class: 'card agent-card', href: `#/agents/${agent.id}` },
    el(
      'div',
      { class: 'row' },
      el('div', { class: 'agent-avatar' }, initials(agent.name)),
      el(
        'div',
        {},
        el('div', { style: 'font-weight:600' }, agent.name),
        el('div', { class: 'muted small' }, agent.kind),
      ),
      el('div', { class: 'spacer' }),
      statusTag(last ? last.status : null),
    ),
    el(
      'div',
      { class: 'stat-row' },
      stat(agent.result_count, 'results'),
      stat(agent.lead_count, 'leads'),
      stat(agent.profiles_per_launch, 'per launch'),
    ),
    el(
      'div',
      { class: 'row-between small muted' },
      el('span', {}, agent.session_connected ? 'Session connected' : 'No session cookie'),
      el('span', {}, last ? `Last run ${timeAgo(last.queued_at)}` : 'Never launched'),
    ),
  );
}

function stat(value, label) {
  return el('div', { class: 'stat' }, el('b', {}, String(value)), el('span', {}, label));
}

async function createAgent() {
  try {
    const agent = await api.createAgent({ name: 'Untitled LinkedIn Profile Scraper' });
    window.location.hash = `#/agents/${agent.id}/setup`;
  } catch (error) {
    toast(error.message, 'err');
  }
}
