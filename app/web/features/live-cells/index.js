// Live cells: the optional step between the populations and the cluster settings of a finished
// gate. It is the part in the population picker's slot 'gate.livecells' (the slot's ctx is
// documented in features/population-picker/index.js); with this feature left out of main.js the
// picker goes straight from the populations to the cluster settings.
import { registerSlot } from '../../shared/views.js';
import { render } from './step.js';

export function mount() {
  registerSlot('gate.livecells', { render });
}
