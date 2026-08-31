import { api } from '../api.js';
import { clear, el, toast } from '../ui.js';

const STEPS = [
  { key: 'input', label: 'Profiles to scrape', render: stepInput },
  { key: 'session', label: 'Connect to LinkedIn', render: stepSession },
  { key: 'email', label: 'Email discovery', render: stepEmail },
  { key: 'behavior', label: 'Behavior', render: stepBehavior },
  { key: 'launch', label: 'Launch settings', render: stepLaunch },
  { key: 'advanced', label: 'Advanced settings', render: stepAdvanced },
];

export async function renderSetup(view, agentId) {
  clear(view);
  let agent = await api.agent(agentId);
  let active = 0;

  const context = {
    get agent() {
      return agent;
    },
    async save(payload) {
      agent = await api.updateAgent(agent.id, payload);
      toast('Saved', 'ok');
      paint();
      return agent;
    },
    async call(fn) {
      agent = await fn(agent);
      toast('Saved', 'ok');
      paint();
      return agent;
    },
    next() {
      active = Math.min(STEPS.length - 1, active + 1);
      paint();
    },
    back() {
      active = Math.max(0, active - 1);
      paint();
    },
  };

  const header = el('div', {});
  const body = el('div', { class: 'wizard' });
  view.append(header, body);

  function paint() {
    clear(header);
    header.append(
      el(
        'div',
        { class: 'row-between', style: 'margin-bottom:24px' },
        el(
          'div',
          {},
          el('div', { class: 'muted small' }, agent.kind),
          el(
            'input',
            {
              type: 'text',
              value: agent.name,
              style: 'font-size:24px;font-weight:650;border:0;padding:0;background:none;width:min(560px,60vw)',
              onChange: (event) => context.save({ name: event.target.value.trim() || agent.name }),
            },
          ),
        ),
        el(
          'div',
          { class: 'row' },
          el('a', { class: 'btn', href: `#/agents/${agent.id}` }, 'Save & close'),
        ),
      ),
    );

    clear(body);
    const nav = el('ul', { class: 'steps' });
    STEPS.forEach((step, index) => {
      nav.append(
        el(
          'li',
          {},
          el(
            'button',
            {
              class: index === active ? 'active' : '',
              onClick: () => {
                active = index;
                paint();
              },
            },
            el('span', { class: 'dot' }, isComplete(step.key, agent) ? '✓' : '·'),
            step.label,
          ),
        ),
      );
    });

    const panel = el('div', { class: 'card' });
    STEPS[active].render(panel, context);
    body.append(nav, panel);
  }

  paint();
}

function isComplete(key, agent) {
  switch (key) {
    case 'input':
      return agent.is_configured;
    case 'session':
      return agent.session_connected;
    case 'email':
      return Boolean(agent.email_provider);
    case 'behavior':
      return true;
    case 'launch':
      return true;
    default:
      return false;
  }
}

function footer(context, onSave, { first = false } = {}) {
  return el(
    'div',
    { class: 'row', style: 'margin-top:22px' },
    first ? null : el('button', { class: 'btn', onClick: () => context.back() }, 'Back'),
    el('button', { class: 'btn btn-primary', onClick: onSave }, 'Save'),
  );
}

function stepInput(panel, context) {
  const agent = context.agent;
  let source = agent.input_source;

  const urlField = el('input', {
    type: 'url',
    placeholder: 'https://www.linkedin.com/in/username/',
    value: agent.input_url || '',
  });
  const listField = el(
    'textarea',
    { placeholder: 'One LinkedIn profile URL per line' },
    (agent.input_urls || []).join('\n'),
  );

  const holder = el('div', { style: 'margin-top:16px' });

  function paintHolder() {
    clear(holder);
    if (source === 'url') {
      holder.append(el('div', { class: 'field' }, el('label', {}, 'Profile URL'), urlField));
    } else if (source === 'list') {
      holder.append(
        el('div', { class: 'field' }, el('label', {}, 'Profile URL list'), listField,
           el('div', { class: 'hint' }, 'Duplicates and unparseable lines are dropped when the run starts.')),
      );
    } else if (source === 'agent') {
      holder.append(
        el(
          'div',
          { class: 'field' },
          el('label', {}, 'Source agent id'),
          el('input', { type: 'number', id: 'source-agent', value: agent.source_agent_id || '' }),
          el('div', { class: 'hint' }, 'Consumes the successful results of another agent as this one’s input.'),
        ),
      );
    } else {
      holder.append(
        el('div', { class: 'notice notice-warn' },
           'The HubSpot connector is not implemented in this build. See docs/INTEGRATIONS.md.'),
      );
    }
  }

  panel.append(
    el('div', { class: 'notice' }, 'Tell the agent which LinkedIn profiles to scrape.'),
    el('label', {}, 'Where the URLs come from'),
    el(
      'div',
      { class: 'choice-grid' },
      [
        ['url', 'A URL'],
        ['list', 'My list'],
        ['agent', 'Another agent'],
        ['hubspot', 'HubSpot'],
      ].map(([key, label]) =>
        el(
          'button',
          {
            class: `choice ${source === key ? 'selected' : ''}`,
            onClick: (event) => {
              source = key;
              panel.querySelectorAll('.choice').forEach((node) => node.classList.remove('selected'));
              event.currentTarget.classList.add('selected');
              paintHolder();
            },
          },
          label,
        ),
      ),
    ),
    holder,
    footer(context, async () => {
      const payload = { input_source: source };
      if (source === 'url') payload.input_url = urlField.value.trim();
      if (source === 'list') {
        payload.input_urls = listField.value.split('\n').map((line) => line.trim()).filter(Boolean);
      }
      if (source === 'agent') {
        payload.source_agent_id = Number(panel.querySelector('#source-agent').value) || null;
      }
      try {
        await context.save(payload);
        context.next();
      } catch (error) {
        toast(error.message, 'err');
      }
    }, { first: true }),
  );

  paintHolder();
}

function stepSession(panel, context) {

  const status = el('div', {}, el('p', { class: 'muted' }, 'Checking…'));
  const grading = el('div', {});

  const cookieField = el('textarea', {
    placeholder:
      'Paste every linkedin.com cookie here.\n\n'
      + 'Either a JSON export from a cookie-editor extension, or the Cookie '
      + 'request header: li_at=...; JSESSIONID=...; bcookie=...',
    style: 'min-height:150px',
  });
  const uaField = el('input', {
    type: 'text',
    placeholder: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 …',
  });

  function paintGrade(summary) {
    clear(grading);
    if (!summary) return;

    const tone = { complete: 'tag-ok', partial: 'tag-warn', minimal: 'tag-err', unusable: 'tag-err' };
    grading.append(
      el(
        'div',
        { class: 'row', style: 'margin:12px 0 8px' },
        el('span', { class: `tag ${tone[summary.grade] || ''}` }, summary.grade),
        el('span', { class: 'muted small' }, `${summary.count} cookies`),
      ),
      el('div', { class: 'hint' }, summary.advice),
      ...(summary.warnings || []).map((warning) =>
        el('div', { class: 'notice notice-warn small', style: 'margin-top:8px' }, warning),
      ),
    );
  }

  panel.append(
    el('h2', {}, 'Connect your LinkedIn account'),
    el(
      'div',
      { class: 'notice' },
      'Best: sign in once by hand on a machine with a screen — `python -m phantom.session '
      + 'login` — then move the profile to the server with `session export` / `session import`. '
      + 'The cookies stay with the browser state that makes them coherent.',
    ),
    el(
      'div',
      { class: 'notice notice-warn' },
      'Otherwise, paste a cookie set below. Copy ALL linkedin.com cookies, not just li_at, '
      + 'and include the user agent of the browser you copied them from. A lone li_at '
      + 'replayed under a different browser identity is what gets accounts signed out.',
    ),
    status,
    el('div', { class: 'field' }, el('label', {}, 'Cookies'), cookieField),
    el(
      'div',
      { class: 'field' },
      el('label', {}, 'User agent of that browser'),
      uaField,
      el('div', { class: 'hint' },
         'In that browser’s console: navigator.userAgent — cookies replayed under a '
         + 'different agent than the one that received them are more likely to be rejected.'),
    ),
    grading,
    el(
      'div',
      { class: 'row', style: 'margin-top:22px' },
      el('button', { class: 'btn', onClick: () => context.back() }, 'Back'),
      el(
        'button',
        {
          class: 'btn',
          onClick: async () => {
            try {
              paintGrade(await api.previewCookies({ raw: cookieField.value }));
            } catch (error) {
              toast(error.message, 'err');
            }
          },
        },
        'Check',
      ),
      el(
        'button',
        {
          class: 'btn btn-primary',
          onClick: async () => {
            try {
              const summary = await api.uploadCookies({
                raw: cookieField.value,
                user_agent: uaField.value.trim() || null,
                viewport_width: window.screen.width,
                viewport_height: window.screen.height,
                timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
                locale: navigator.language,
              });
              paintGrade(summary);
              cookieField.value = '';
              toast('Cookies stored', 'ok');
              refresh();
            } catch (error) {
              toast(error.message, 'err');
            }
          },
        },
        'Save cookies',
      ),
      el('div', { class: 'spacer' }),
      el('button', { class: 'btn btn-primary', onClick: () => context.next() }, 'Continue'),
    ),
  );

  function refresh() {
    api
      .session()
      .then((state) => {
        clear(status);
        status.append(
          el(
            'div',
            { class: 'row', style: 'margin-bottom:14px' },
            el(
              'span',
              { class: `tag ${state.logged_in ? 'tag-ok' : 'tag-warn'}` },
              state.logged_in ? 'Signed in' : 'Not signed in',
            ),
            el('span', { class: 'muted small' }, state.summary),
            el('div', { class: 'spacer' }),
            state.source === 'cookies'
              ? el(
                  'button',
                  {
                    class: 'btn btn-sm btn-danger',
                    onClick: async () => {
                      await api.clearCookies();
                      toast('Stored cookies removed');
                      refresh();
                    },
                  },
                  'Remove',
                )
              : null,
          ),
        );
      })
      .catch((error) => {
        clear(status);
        status.append(el('div', { class: 'notice notice-err' }, error.message));
      });
  }

  refresh();
}

function stepEmail(panel, context) {
  const agent = context.agent;
  const providerField = el(
    'select',
    {},
    [
      ['none', 'None'],
      ['hunter', 'Hunter.io'],
      ['dropcontact', 'Dropcontact'],
    ].map(([value, label]) =>
      el('option', { value, selected: (agent.email_provider || 'none') === value }, label),
    ),
  );
  const keyField = el('input', {
    type: 'password',
    placeholder: agent.email_key_set ? 'A key is stored — enter a new one to replace it' : 'API key',
    autocomplete: 'off',
  });

  panel.append(
    el(
      'div',
      { class: 'notice' },
      'Optional. One credit is spent per profile on an attempt to find a verified professional '
      + 'address. A miss still costs the credit, which is why this is off by default.',
    ),
    el('div', { class: 'field' }, el('label', {}, 'Email discovery service'), providerField),
    el('div', { class: 'field' }, el('label', {}, 'API key'), keyField),
    footer(context, async () => {
      try {
        await context.call((current) =>
          api.setEmailProvider(current.id, {
            provider: providerField.value,
            api_key: keyField.value.trim() || null,
          }),
        );
        context.next();
      } catch (error) {
        toast(error.message, 'err');
      }
    }),
  );
}

function stepBehavior(panel, context) {
  const agent = context.agent;
  const limitField = el('input', { type: 'number', min: 1, max: 1500, value: agent.profiles_per_launch });
  const companyBox = el('input', { type: 'checkbox', id: 'enrich', checked: agent.enrich_company_data });
  const allSectionsBox = el('input', {
    type: 'checkbox',
    id: 'all-sections',
    checked: agent.fetch_all_sections,
  });
  const pictureBox = el('input', { type: 'checkbox', id: 'picture', checked: agent.save_profile_picture });
  const skipBox = el('input', { type: 'checkbox', id: 'skip', checked: agent.skip_already_processed });
  const minField = el('input', { type: 'number', min: 0, step: '0.5', value: agent.min_delay_seconds ?? '' });
  const maxField = el('input', { type: 'number', min: 0, step: '0.5', value: agent.max_delay_seconds ?? '' });

  panel.append(
    el(
      'div',
      { class: 'notice' },
      'Stay under roughly 1500 profiles a day. The limit that matters is the account, not the '
      + 'IP — a restricted account is rarely reinstated.',
    ),
    el('div', { class: 'field' }, el('label', {}, 'Profiles per launch'), limitField),
    el(
      'div',
      { class: 'field check' },
      companyBox,
      el(
        'div',
        {},
        el('label', { for: 'enrich' }, 'Enrich profiles with company data'),
        el('div', { class: 'hint' }, 'Costs one extra page load per distinct company.'),
      ),
    ),
    el(
      'div',
      { class: 'field check' },
      allSectionsBox,
      el(
        'div',
        {},
        el('label', { for: 'all-sections' }, 'Fetch every entry of every section'),
        el('div', { class: 'hint' },
           'The profile page shows only the first two or three entries per section. This '
           + 'visits each “Show all” page, which is the difference between three skills and '
           + 'all of them — at one extra page view per section, per profile.'),
      ),
    ),
    el(
      'div',
      { class: 'field check' },
      pictureBox,
      el(
        'div',
        {},
        el('label', { for: 'picture' }, 'Save each profile picture as a JPEG'),
        el('div', { class: 'hint' }, 'Written to the data directory and served under /pictures.'),
      ),
    ),
    el(
      'div',
      { class: 'field check' },
      skipBox,
      el(
        'div',
        {},
        el('label', { for: 'skip' }, 'Skip profiles this agent has already scraped'),
        el('div', { class: 'hint' },
           'Off means every launch re-scrapes the full input and appends a fresh row.'),
      ),
    ),
    el(
      'div',
      { class: 'row', style: 'margin-top:16px;gap:16px;align-items:flex-end' },
      el('div', { style: 'flex:1' }, el('label', {}, 'Minimum delay between profiles (s)'), minField),
      el('div', { style: 'flex:1' }, el('label', {}, 'Maximum delay (s)'), maxField),
    ),
    el('div', { class: 'hint' }, 'Left blank, the server defaults apply. Requests are spaced by a '
      + 'random value in this range — a constant interval is itself a signature.'),
    footer(context, async () => {
      try {
        await context.save({
          profiles_per_launch: Number(limitField.value) || 200,
          enrich_company_data: companyBox.checked,
          fetch_all_sections: allSectionsBox.checked,
          save_profile_picture: pictureBox.checked,
          skip_already_processed: skipBox.checked,
          min_delay_seconds: minField.value === '' ? null : Number(minField.value),
          max_delay_seconds: maxField.value === '' ? null : Number(maxField.value),
        });
        context.next();
      } catch (error) {
        toast(error.message, 'err');
      }
    }),
  );
}

function stepLaunch(panel, context) {
  const agent = context.agent;
  let frequency = agent.frequency;

  const cronField = el(
    'select',
    {},
    [
      ['every:30m', 'Every 30 minutes'],
      ['every:1h', 'Every hour'],
      ['every:6h', 'Every 6 hours'],
      ['every:1d', 'Every day'],
    ].map(([value, label]) =>
      el('option', { value, selected: agent.schedule_cron === value }, label),
    ),
  );
  const chainField = el('input', { type: 'number', value: agent.chain_to_agent_id || '' });
  const holder = el('div', { style: 'margin-top:16px' });

  function paintHolder() {
    clear(holder);
    if (frequency === 'repeatedly') {
      holder.append(el('div', { class: 'field' }, el('label', {}, 'Interval'), cronField));
    } else if (frequency === 'after_agent') {
      holder.append(
        el(
          'div',
          { class: 'field' },
          el('label', {}, 'Launch this agent after agent id'),
          chainField,
          el('div', { class: 'hint' },
             'Set on the upstream agent: it queues this one when a run finishes successfully.'),
        ),
      );
    } else {
      holder.append(el('div', { class: 'hint' }, 'The agent runs only when you press Launch.'));
    }
  }

  panel.append(
    el('h2', {}, 'Launch frequency'),
    el(
      'div',
      { class: 'choice-grid' },
      [
        ['once', 'Manually'],
        ['repeatedly', 'Repeatedly'],
        ['after_agent', 'After another agent'],
      ].map(([key, label]) =>
        el(
          'button',
          {
            class: `choice ${frequency === key ? 'selected' : ''}`,
            onClick: (event) => {
              frequency = key;
              panel.querySelectorAll('.choice').forEach((node) => node.classList.remove('selected'));
              event.currentTarget.classList.add('selected');
              paintHolder();
            },
          },
          label,
        ),
      ),
    ),
    holder,
    footer(context, async () => {
      const payload = { frequency, schedule_enabled: frequency === 'repeatedly' };
      if (frequency === 'repeatedly') payload.schedule_cron = cronField.value;
      if (frequency === 'after_agent') payload.chain_to_agent_id = Number(chainField.value) || null;
      try {
        await context.save(payload);
        context.next();
      } catch (error) {
        toast(error.message, 'err');
      }
    }),
  );

  paintHolder();
}

function stepAdvanced(panel, context) {
  const agent = context.agent;
  const execField = el('input', { type: 'number', min: 0, max: 300, value: agent.max_execution_minutes });
  const retryField = el('input', { type: 'number', min: 0, max: 10, value: agent.max_launch_retries });
  const webhookField = el('input', { type: 'url', value: agent.webhook_url || '', placeholder: 'https://…' });

  panel.append(
    el('h2', {}, 'Limits and notifications'),
    el(
      'div',
      { class: 'field' },
      el('label', {}, 'Maximum execution time per launch (minutes)'),
      execField,
      el('div', { class: 'hint' }, '0 uses the server default. The limit is checked between profiles, '
        + 'so a run stops cleanly rather than mid-request.'),
    ),
    el(
      'div',
      { class: 'field' },
      el('label', {}, 'Maximum launch retries'),
      retryField,
      el('div', { class: 'hint' }, 'A failed launch is re-queued this many times before it stays failed.'),
    ),
    el(
      'div',
      { class: 'field' },
      el('label', {}, 'Webhook URL'),
      webhookField,
      el('div', { class: 'hint' }, 'Receives a JSON POST with the launch summary when a run ends. '
        + 'Best effort — a webhook failure never fails the launch.'),
    ),
    el(
      'div',
      { class: 'row', style: 'margin-top:22px' },
      el('button', { class: 'btn', onClick: () => context.back() }, 'Back'),
      el(
        'button',
        {
          class: 'btn btn-primary',
          onClick: () =>
            context
              .save({
                max_execution_minutes: Number(execField.value) || 0,
                max_launch_retries: Number(retryField.value) || 0,
                webhook_url: webhookField.value.trim() || null,
              })
              .catch((error) => toast(error.message, 'err')),
        },
        'Save',
      ),
      el('div', { class: 'spacer' }),
      el(
        'button',
        {
          class: 'btn btn-danger',
          onClick: async () => {
            if (!window.confirm('Delete this agent and every result it produced? This cannot be undone.')) return;
            await api.deleteAgent(agent.id);
            window.location.hash = '#/';
          },
        },
        'Delete agent',
      ),
    ),
  );
}
