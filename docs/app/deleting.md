# Deleting files and gates

What the explorer deletes, and what the server refuses. Both deletes use routes the server
already had, `DELETE /uploads/{uid}` and `DELETE /flow/gates/{gid}` (contract sections 3.3 and
3.4); the server is unchanged.

## In the explorer

Each file under Datasets and each gate under Gates has a delete button at the end of its row. It
shows while the pointer is over the row or the button has the keyboard focus, and always on a
touch screen. It opens a dialog that names the file or the gate and says what goes with it:

- A file: it leaves the workspace for good, and a file that a gate uses is kept until that gate is
  deleted.
- A gate: its populations, figures and live-cells sets go with it, and the runs made from it keep
  their results.

The focus starts on Cancel, so the Enter that pressed the delete button cannot delete as well; Tab
moves to Delete. Cancel and Escape shut the dialog, delete nothing and put the focus back on the
delete button, or on the one drawn in its place when the explorer redrew meanwhile (it redraws as
jobs move). No key goes past the dialog: Escape closes no drawer or menu behind it, and no
shortcut, such as Backspace stepping a plot back, acts on the page under it.

Delete sends the request. While it is on its way the button is dimmed and does nothing, through
any redraw of the explorer. Once the server has deleted the item:

- the item leaves the explorer and the workspace the page holds (a gate leaves the store's gate
  cache too, which would still answer for it);
- its tabs close: a file's tab, or a gate's tab and its figures' tabs. When the active tab is one
  of them, the next tab left takes over, or else the one before it, as closing it yourself does;
- a toast and a line in the Activity log say what was deleted;
- a workspace reload, or a gate's own answer, that was on its way when the delete landed leaves
  the item out, since the server may have made it before the delete.

**Delete this workspace** in the workspace menu asks in the same dialog, with the focus on Cancel.
Its menu item goes with the menu, so Cancel puts the focus on the workspace button.

## What the server refuses

Each refusal is 409 `wrong_state`. The item stays as it was, its button works again and has the
focus back, and the server's words show in a toast and in the Activity log, after the name of what
was to be deleted.

- A file that a gate uses: `Gate g1 uses this file; delete it first.` Delete that gate, then the
  file.
- A gate whose job is still running: cancel the job first.
- A gate with a run from it that is queued or running, or with a live-cells set that is still
  loading.

A run is made from its gate's files, and once it is done it keeps its own outputs. Deleting the
gate and then its files leaves the run's plot, Compare, box plots, files and record as they were.

## Fixture mode

A file read in the tab was never sent. Its delete removes it from the tab, and the fixture
transport forgets its colour channel set, as the server forgets a deleted upload's when it makes
room for a dataset name. The recorded workspace's uploads and gates have no DELETE fixture, so
deleting one shows the missing-fixture error (contract section 6).
