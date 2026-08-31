

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: options.body ? { 'Content-Type': 'application/json' } : {},
    ...options,
  });

  if (response.status === 204) return null;

  const text = await response.text();
  let body = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }

  if (!response.ok) {
    const detail = body && body.detail ? body.detail : `${response.status} ${response.statusText}`;
    const error = new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    error.status = response.status;
    throw error;
  }
  return body;
}

const json = (method) => (path, payload) =>
  request(path, { method, body: payload === undefined ? undefined : JSON.stringify(payload) });

export const api = {
  get: (path) => request(path),
  post: json('POST'),
  patch: json('PATCH'),
  put: json('PUT'),
  del: (path) => request(path, { method: 'DELETE' }),

  columns: () => request('/api/columns'),
  quota: () => request('/api/quota'),
  session: () => request('/api/session'),
  previewCookies: (payload) => json('POST')('/api/session/cookies/preview', payload),
  uploadCookies: (payload) => json('PUT')('/api/session/cookies', payload),
  clearCookies: () => request('/api/session/cookies', { method: 'DELETE' }),

  agents: () => request('/api/agents'),
  agent: (id) => request(`/api/agents/${id}`),
  createAgent: (payload) => json('POST')('/api/agents', payload),
  updateAgent: (id, payload) => json('PATCH')(`/api/agents/${id}`, payload),
  deleteAgent: (id) => request(`/api/agents/${id}`, { method: 'DELETE' }),

  setSession: (id, payload) => json('PUT')(`/api/agents/${id}/session`, payload),
  clearSession: (id) => request(`/api/agents/${id}/session`, { method: 'DELETE' }),
  setEmailProvider: (id, payload) => json('PUT')(`/api/agents/${id}/email-provider`, payload),

  launch: (id) => json('POST')(`/api/agents/${id}/launch`),
  launches: (id) => request(`/api/agents/${id}/launches`),
  cancelLaunch: (launchId) => json('POST')(`/api/launches/${launchId}/cancel`),
  logs: (launchId, after = 0) => request(`/api/launches/${launchId}/logs?after=${after}`),

  results: (id, { page = 1, perPage = 10 } = {}) =>
    request(`/api/agents/${id}/results?page=${page}&per_page=${perPage}`),
  leads: (id, { page = 1, perPage = 10 } = {}) =>
    request(`/api/agents/${id}/leads?page=${page}&per_page=${perPage}`),
};
