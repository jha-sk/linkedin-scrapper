

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'html') node.innerHTML = value;
    else if (key.startsWith('on') && typeof value === 'function') {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (key === 'dataset') Object.assign(node.dataset, value);
    else node.setAttribute(key, value === true ? '' : String(value));
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
  return node;
}

export function toast(message, kind = '') {
  const host = document.getElementById('toasts');
  const node = el('div', { class: `toast ${kind}` }, message);
  host.append(node);
  setTimeout(() => {
    node.style.opacity = '0';
    node.style.transition = 'opacity 200ms ease';
    setTimeout(() => node.remove(), 220);
  }, kind === 'err' ? 6000 : 3200);
}

export function initials(name) {
  return (name || '?')
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word[0].toUpperCase())
    .join('');
}

export function timeAgo(iso) {
  if (!iso) return '—';
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  const steps = [
    [60, 's'],
    [3600, 'm', 60],
    [86400, 'h', 3600],
    [2592000, 'd', 86400],
  ];
  if (seconds < 60) return `${Math.floor(seconds)}s ago`;
  for (const [limit, unit, divisor] of steps.slice(1)) {
    if (seconds < limit) return `${Math.floor(seconds / divisor)}${unit} ago`;
  }
  return new Date(iso).toLocaleDateString();
}

export function clockTime(iso) {
  return new Date(iso).toLocaleTimeString([], { hour12: false });
}

export function statusTag(status) {
  const map = {
    finished: ['tag-ok', 'Finished'],
    running: ['tag-run', 'Running'],
    queued: ['tag-run', 'Queued'],
    failed: ['tag-err', 'Failed'],
    cancelled: ['tag-warn', 'Cancelled'],
  };
  const [cls, label] = map[status] || ['', status || 'Never run'];
  return el('span', { class: `tag ${cls}` }, label);
}

export function progressBar(value, idle = false) {
  return el(
    'div',
    { class: `progress ${idle ? 'idle' : ''}` },
    el('i', { style: `width:${Math.round((value || 0) * 100)}%` }),
  );
}

export function confirmAction(message) {
  return window.confirm(message);
}
