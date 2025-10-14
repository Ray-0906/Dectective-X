const DEFAULT_BASE_URL = 'http://127.0.0.1:8000';
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? DEFAULT_BASE_URL;

async function request(path, options = {}) {
  const url = `${API_BASE_URL}${path}`;
  const isFormData = options.body instanceof FormData;
  const customHeaders = options.headers ?? {};
  const headers = {
    ...(!isFormData && !('Content-Type' in customHeaders) ? { 'Content-Type': 'application/json' } : {}),
    ...customHeaders,
  };

  const response = await fetch(url, {
    headers,
    ...options,
  });

  const isJson = response.headers.get('content-type')?.includes('application/json');
  const payload = isJson ? await response.json() : await response.text();

  if (!response.ok) {
    const message = payload?.detail || payload?.message || response.statusText || 'Unknown error';
    throw new Error(message);
  }

  return payload;
}

export async function healthCheck() {
  try {
    const result = await request('/health', { method: 'GET' });
    return { ok: true, result };
  } catch (error) {
    return { ok: false, error };
  }
}

export async function uploadUfdr(file) {
  const formData = new FormData();
  formData.append('file', file);
  return request('/upload-ufdr', {
    method: 'POST',
    body: formData,
  });
}

export async function triggerIngest({ caseId, reset = true, dataPath = null }) {
  const body = {
    case_id: caseId,
    reset,
    ...(dataPath ? { data_path: dataPath } : {}),
  };
  return request('/ingest', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export async function runQuery({ query, limit = 5 }) {
  return request('/query', {
    method: 'POST',
    body: JSON.stringify({ query, limit }),
  });
}

export { API_BASE_URL };
