

export const config = {

  runtime: 'nodejs',
  maxDuration: 60,
};

const HOP_BY_HOP = new Set([
  'connection',
  'keep-alive',
  'transfer-encoding',
  'upgrade',
  'host',
  'content-length',
]);

function backendUrl(req) {
  const base = process.env.BACKEND_URL;
  if (!base) return null;

  const [pathname, query] = req.url.split('?');
  const suffix = query ? `?${query}` : '';
  return `${base.replace(/\/$/, '')}${pathname}${suffix}`;
}

async function readBody(req) {
  if (req.method === 'GET' || req.method === 'HEAD') return undefined;
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  return chunks.length ? Buffer.concat(chunks) : undefined;
}

export default async function handler(req, res) {
  const target = backendUrl(req);
  if (!target) {
    res.status(500).json({
      detail:
        'BACKEND_URL is not set. Add it in the Vercel project settings, ' +
        'pointing at your server, e.g. https://scraper.example.com',
    });
    return;
  }

  const headers = {};
  for (const [name, value] of Object.entries(req.headers)) {
    if (!HOP_BY_HOP.has(name.toLowerCase())) headers[name] = value;
  }
  if (process.env.BACKEND_TOKEN) {
    headers.authorization = `Bearer ${process.env.BACKEND_TOKEN}`;
  }

  let upstream;
  try {
    upstream = await fetch(target, {
      method: req.method,
      headers,
      body: await readBody(req),
      redirect: 'manual',
    });
  } catch (error) {

    res.status(502).json({
      detail: `Could not reach the backend at ${process.env.BACKEND_URL}: ${error.message}`,
    });
    return;
  }

  res.status(upstream.status);
  upstream.headers.forEach((value, name) => {
    if (!HOP_BY_HOP.has(name.toLowerCase())) res.setHeader(name, value);
  });

  const contentType = upstream.headers.get('content-type') || '';
  if (contentType.includes('text/event-stream')) {

    res.setHeader('Cache-Control', 'no-cache, no-transform');
    res.setHeader('X-Accel-Buffering', 'no');
    if (typeof res.flushHeaders === 'function') res.flushHeaders();
  }

  if (!upstream.body) {
    res.end();
    return;
  }

  const reader = upstream.body.getReader();
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      res.write(Buffer.from(value));
    }
  } catch {

  } finally {
    res.end();
  }
}
