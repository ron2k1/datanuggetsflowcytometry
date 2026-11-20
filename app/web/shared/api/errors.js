// The API's error shape (contract section 3) as a thrown Error: message, HTTP status, code, param.
export class ApiError extends Error {
  constructor(status, body) {
    const e = (body && body.error) || {};
    super(e.message || `Request failed (${status})`);
    this.status = status; this.code = e.code || 'internal'; this.param = e.param || null;
  }
}
