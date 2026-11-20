// The one door to the server. With ?fixtures=1 (or localStorage dn-fixtures = "1") every call
// reads a recorded fixture instead; callers never choose, they call api.<endpoint>().
import { STORAGE } from '../config.js';
import * as live from './live.js';
import * as recorded from './fixtures.js';
import { makeClient } from './client.js';

function storedFlag() {
  try { return localStorage.getItem(STORAGE.fixtures) === '1'; } catch (e) { return false; }
}
export const FIXTURES = new URLSearchParams(location.search).get('fixtures') === '1' || storedFlag();

/** @type {import('./client.js').ApiClient} */
export const api = makeClient(FIXTURES ? recorded : live);
