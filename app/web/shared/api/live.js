// The live transport: every call goes to the server under /api/v1.
import { API_BASE } from '../config.js';
import { ApiError } from './errors.js';

export async function request(method, path, body) {
  const init = { method, credentials: 'same-origin', headers: { Accept: 'application/json' } };
  if (body !== undefined) { init.headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(body); }
  let r;
  try { r = await fetch(API_BASE + path, init); } catch (e) {
    throw new ApiError(0, { error: { code: 'network', message: 'The server did not answer. Is it running?', param: null } });
  }
  if (r.status === 204) return null;
  let data = null;
  try { data = await r.json(); } catch (e) { data = null; }
  if (!r.ok) throw new ApiError(r.status, data);
  return data;
}

// POST /uploads, multipart field "file", with upload progress.
export function upload(file, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', API_BASE + '/uploads');
    xhr.withCredentials = true;
    xhr.responseType = 'json';
    xhr.upload.onprogress = e => { if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total); };
    xhr.onload = () => (xhr.status >= 200 && xhr.status < 300 ? resolve(xhr.response) : reject(new ApiError(xhr.status, xhr.response)));
    xhr.onerror = () => reject(new ApiError(0, { error: { code: 'network', message: 'The upload was interrupted.', param: null } }));
    const fd = new FormData();
    fd.append('file', file, file.name);
    xhr.send(fd);
  });
}

export async function fileUrl(rid, name) {
  return `${API_BASE}/runs/${encodeURIComponent(rid)}/files/${encodeURIComponent(name)}`;
}
export const zipUrl = rid => `${API_BASE}/runs/${encodeURIComponent(rid)}/download.zip`;
