// Upload: the uploader (file chooser, drops, progress in S.inflight) and the upload tab
// (channel stats, then the parts in slot 'upload.fcs').
import { wireUploader } from './uploader.js';
import { registerUploadView } from './view.js';

export function mount() { wireUploader(); registerUploadView(); }
