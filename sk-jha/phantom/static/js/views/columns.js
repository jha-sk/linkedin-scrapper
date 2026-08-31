import { api } from '../api.js';
import { clear, el } from '../ui.js';

export async function renderColumns(view) {
  clear(view);
  const columns = await api.columns();

  view.append(
    el('h1', {}, 'Data schema'),
    el(
      'p',
      { class: 'muted', style: 'max-width:70ch' },
      `Every result row carries all ${columns.length} columns, in this order, whether or not a `
      + 'value was found. CSV export writes the labels as the header row and the keys as the '
      + 'machine contract — adding a column is safe for consumers, renaming one is not.',
    ),
    el(
      'div',
      { class: 'table-wrap' },
      el(
        'table',
        {},
        el('thead', {}, el('tr', {},
          el('th', {}, '#'), el('th', {}, 'Key'), el('th', {}, 'Label'), el('th', {}, 'Type'))),
        el(
          'tbody',
          {},
          columns.map((column, index) =>
            el(
              'tr',
              {},
              el('td', { class: 'muted' }, String(index + 1)),
              el('td', { class: 'mono' }, column.key),
              el('td', {}, column.label),
              el('td', { class: 'muted' }, column.kind),
            ),
          ),
        ),
      ),
    ),
  );
}
