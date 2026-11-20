// Jobs: polling every queued or running job (EV.jobStarted starts one) and the job tab.
import { wirePolling } from './poll.js';
import { registerJobView } from './view.js';

export function mount() { wirePolling(); registerJobView(); }
