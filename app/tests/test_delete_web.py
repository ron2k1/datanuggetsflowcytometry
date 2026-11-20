"""Deleting a file or a gate from the explorer, and the confirm every delete asks through, run in
Node on the page harness of test_datasets_page_web (fixture mode, the recorded workspace and its
copies of the PBMC uploads; docs/app/deleting.md). The fixture transport records no DELETE
answer, so DELETE /uploads/{uid} and DELETE /flow/gates/{gid} answer 204 here and the ids they
were sent are kept in deleted; a file read in the tab goes through the real transport."""

from __future__ import annotations

import pytest

import test_datasets_page_web as harness

# The harness's fixtures, under the names pytest finds them by.
page, panels = harness.page, harness.panels
read_in_tab = harness.read_in_tab
pytestmark = pytest.mark.skipif(harness.NODE is None, reason="node isn't installed")

# The dialog on the page, a button of a node by its label, and the stand-in DELETEs.
HELPERS = (
    "const dialog = () => document.body.find('confirm');"
    " const button = (n, label) => n.findAll('btn').find(b => b.textContent === label);"
    " const said = d => [d.find('confirm-title').textContent, d.find('confirm-text').textContent];"
    " const { ApiError } = await import('./shared/api/errors.js');"
    " const real = { upload: api.deleteUpload, gate: api.deleteGate }, deleted = [];"
    " api.deleteUpload = async uid => { deleted.push(uid); return null; };"
    " api.deleteGate = async gid => { deleted.push(gid); return null; };"
)
FILE_TEXT = (
    "The file is removed from this workspace and cannot be restored. A file that a gate uses is"
    " kept until the gate is deleted."
)
GATE_TEXT = (
    "Its populations, figures and live-cells sets are removed and cannot be restored. Runs made"
    " from it keep their results."
)


def test_a_files_delete_asks_first_with_the_focus_on_cancel(page):
    """Each file's row has a delete button. It opens a dialog naming the file, with the focus on
    Cancel, so the Enter that pressed the button cannot delete too. Delete sends DELETE
    /uploads/{uid}; the file's tab closes, the tab after it, or else before it, takes over, and
    the file leaves the explorer and the workspace. The active file's row is marked across its
    delete button too."""
    got = page(
        HELPERS + " const u = S.ws.uploads.find(x => x.name === 'x1.fcs');"
        " emit(EV.openTab, { key: 'local' }); emit(EV.openTab, { key: `upload:${u.id}` });"
        " const lit = [item('x1.fcs').classList.contains('is-active'), item('x2.fcs').classList.contains('is-active')];"
        " item('x1.fcs').find('tree-act').click(); const d = dialog();"
        " const asked = [...said(d), d.open, document.activeElement.textContent, d.findAll('btn').map(b => b.textContent)];"
        " button(d, 'Delete').click(); await tick();"
        " return [lit, asked, deleted, dialog(), S.tabs, rows().some(r => r[1] === 'x1.fcs'), S.ws.uploads.some(x => x.id === u.id),"
        " $('#toast').textContent, S.activity.at(-1).msg];"
    )
    lit, asked, sent, left, tabs, listed, held, toast, log = got
    assert lit == [True, False]
    assert asked == ["Delete x1.fcs?", FILE_TEXT, True, "Cancel", ["Cancel", "Delete"]]
    assert sent == ["x1"]
    assert left is None
    assert tabs == {"open": ["start", "local"], "active": "local"}
    assert [listed, held] == [False, False]
    assert [toast, log] == ["Deleted x1.fcs.", "Deleted x1.fcs"]


def test_cancel_deletes_nothing_and_gives_the_focus_back(page):
    """Cancel shuts the dialog, sends nothing and puts the focus back on the delete button. No
    key pressed in the dialog goes further: Escape closes no drawer behind it (the explorer's,
    open at phone width, stays) and Backspace steps no view back."""
    got = page(
        HELPERS + "window.innerWidth = 700; $('#btn-files').click();"
        " const act = item('x1.fcs').find('tree-act'); act.click();"
        " const esc = press(document.activeElement, 'Escape'), back = press(document.activeElement, 'Backspace');"
        " button(dialog(), 'Cancel').click(); await tick();"
        " return [deleted, dialog(), document.activeElement === act, esc.stopped, back.stopped,"
        " $('#explorer').classList.contains('open'), rows().some(r => r[1] === 'x1.fcs')];"
    )
    assert got == [[], None, True, True, True, True, True]


def test_a_redraw_under_the_dialog_keeps_the_focus_and_the_dimming(page):
    """The explorer redraws as jobs move, so the button a dialog came from can be drawn anew
    while the dialog is open. Cancel then puts the focus on the button drawn in its place, and
    Delete dims that one while the request is on its way."""
    got = page(
        HELPERS + " let go; const held = new Promise(ok => { go = ok; });"
        " api.deleteUpload = async uid => { deleted.push(uid); await held; return null; };"
        " const first = item('x1.fcs').find('tree-act'); first.click(); emit(EV.render);"
        " button(dialog(), 'Cancel').click(); await tick();"
        " const now = item('x1.fcs').find('tree-act'), back = [now !== first, document.activeElement === now];"
        " now.click(); emit(EV.render); button(dialog(), 'Delete').click(); await tick();"
        " const dimmed = item('x1.fcs').find('tree-act').disabled; go(); await tick(); await tick();"
        " return [back, dimmed, deleted, rows().some(r => r[1] === 'x1.fcs')];"
    )
    assert got == [[True, True], True, ["x1"], False]


def test_a_refused_delete_keeps_the_file_with_the_servers_words(page):
    """The server refuses a file a gate uses (409). The file stays, and its button, drawn anew
    by a redraw while the request was on its way, works again and has the focus back: a press
    opens the dialog once more. The server's words show in a toast and the activity log."""
    got = page(
        HELPERS
        + " const why = 'Gate g1 uses this file; delete it first.'; let go; const held = new Promise(ok => { go = ok; });"
        " api.deleteUpload = async () => { await held; throw new ApiError(409, { error: { code: 'wrong_state', message: why, param: null } }); };"
        " item('190.fcs').find('tree-act').click(); button(dialog(), 'Delete').click(); await tick();"
        " emit(EV.render); const busy = item('190.fcs').find('tree-act').disabled; go(); await tick(); await tick();"
        " const act = item('190.fcs').find('tree-act'), after = [act.disabled, document.activeElement === act];"
        " act.click();"
        " return [$('#toast').textContent, $('#toast').classList.contains('err'), S.activity.at(-1).msg,"
        " busy, after, said(dialog()), S.ws.uploads.some(x => x.name === '190.fcs')];"
    )
    why = "Gate g1 uses this file; delete it first."
    assert got == [
        why, True, f"Delete 190.fcs: {why}", True, [False, True], ["Delete 190.fcs?", FILE_TEXT], True,
    ]  # fmt: skip


def test_no_second_delete_is_sent_while_one_is_on_its_way(page):
    """The delete button is off while its request is on its way, so a second press opens no
    second dialog and sends nothing more."""
    got = page(
        HELPERS + " let go; const held = new Promise(ok => { go = ok; });"
        " api.deleteUpload = async uid => { deleted.push(uid); await held; return null; };"
        " const act = item('x1.fcs').find('tree-act'); act.click(); button(dialog(), 'Delete').click();"
        " await tick(); const busy = act.disabled; act.click();"
        " const second = dialog(); go(); await tick(); await tick();"
        " return [busy, second, deleted];"
    )
    assert got == [True, None, ["x1"]]


def test_a_gates_delete_closes_its_tabs_and_forgets_it(page):
    """Each gate's row has a delete button too. Delete sends DELETE /flow/gates/{gid}, closes the
    gate's tab and its figures', drops the gate from the store's gate cache (which would
    otherwise still answer for it) and from the explorer."""
    got = page(
        HELPERS
        + " for (const key of ['gate:g1', 'figure:g1:gates', 'local', 'figure:g1:gates']) emit(EV.openTab, { key });"
        " S.cache.gate.g1 = S.ws.gates[0];"
        " item('Gate g1').find('tree-act').click(); const asked = said(dialog());"
        " button(dialog(), 'Delete').click(); await tick();"
        " const { gateById } = await import('./shared/store.js');"
        " return [asked, deleted, S.tabs, gateById('g1'), rows().filter(r => r[1] === 'Gates' || r[1] === 'Gate g1'),"
        " $('#toast').textContent];"
    )
    asked, sent, tabs, cached, listed, toast = got
    assert asked == ["Delete gate g1?", GATE_TEXT]
    assert sent == ["g1"]
    assert tabs == {"open": ["start", "local"], "active": "local"}
    assert cached is None
    assert listed == [[0, "Gates", "0", None, None]]
    assert toast == "Deleted gate g1."


def test_a_reload_on_its_way_brings_no_deleted_item_back(page):
    """A job that ends reloads the workspace, and a tab opening a gate fetches it. When a delete
    lands while those are on their way, their answers, which the server may have made before the
    delete, leave the deleted file and gate out of the workspace, the gate cache and the
    explorer."""
    got = page(
        HELPERS + " const { loadWorkspace, getGate, gateById } = await import('./shared/store.js');"
        " const get = api.workspace; let go, answered;"
        " const held = new Promise(ok => { go = ok; }), onItsWay = new Promise(ok => { answered = ok; });"
        " api.workspace = async () => { const ws = await get(); answered(); await held; return ws; };"
        " api.gate = async gid => { await held; return { ...S.ws.gates.find(g => g.id === gid) }; };"
        " const reload = loadWorkspace(), fetched = getGate('g1'); await onItsWay;"
        " item('x1.fcs').find('tree-act').click(); button(dialog(), 'Delete').click(); await tick();"
        " item('Gate g1').find('tree-act').click(); button(dialog(), 'Delete').click(); await tick();"
        " go(); await reload; await fetched; emit(EV.render);"
        " return [deleted, S.ws.uploads.some(u => u.name === 'x1.fcs'), S.ws.gates.some(g => g.id === 'g1'),"
        " gateById('g1'), rows().some(r => r[1] === 'x1.fcs' || r[1] === 'Gate g1'), S.ws.uploads.length > 0];"
    )
    assert got == [["x1", "g1"], False, False, None, False, True]


def test_the_workspace_delete_asks_in_the_dialog_and_gives_the_focus_back(page):
    """Delete this workspace, in the workspace menu, asks in the same dialog with the focus on
    Cancel. The menu item it came from goes with its menu, so Cancel puts the focus on the
    workspace button, as the menu does after its other items."""
    got = page(
        HELPERS + " let sent = 0; api.deleteWorkspace = async () => { sent += 1; return null; };"
        " $('#btn-ws').click(); document.body.findAll('mi').find(b => b.textContent === 'Delete this workspace').click();"
        " const d = dialog(), asked = [...said(d), document.activeElement.textContent, d.findAll('btn').map(b => b.textContent)];"
        " button(d, 'Cancel').click(); await tick();"
        " return [asked, sent, dialog(), document.activeElement === $('#btn-ws')];"
    )
    assert got == [
        [
            "Delete this workspace?",
            "Every upload, gate, run and job in it is removed and cannot be restored.",
            "Cancel",
            ["Cancel", "Delete workspace"],
        ],
        0,
        None,
        True,
    ]


def test_escape_in_the_dialog_closes_only_the_dialog(page):
    """Escape shuts the dialog as Cancel does, and goes no further: the explorer's drawer, open
    at phone width, stays open and nothing is deleted."""
    got = page(
        HELPERS + " let sent = 0; api.deleteWorkspace = async () => { sent += 1; return null; };"
        " window.innerWidth = 700; $('#btn-files').click();"
        " $('#btn-ws').click(); document.body.findAll('mi').find(b => b.textContent === 'Delete this workspace').click();"
        " const esc = press(document.activeElement, 'Escape'); dialog().close(''); await tick();"
        " return [esc.stopped, sent, dialog(), $('#explorer').classList.contains('open')];"
    )
    assert got == [True, 0, None, True]


def test_a_file_read_in_the_tab_is_deleted_in_the_tab(page, panels):
    """In fixture mode a file read in the tab was never sent, so the fixture transport answers
    its DELETE itself: the file leaves the tab's uploads and the explorer."""
    got = page(
        read_in_tab(panels) + HELPERS + " api.deleteUpload = real.upload;"
        " emit(EV.filesDrop, { files: [await file('202.fcs')] }); await until(1);"
        " item('202.fcs').find('tree-act').click(); button(dialog(), 'Delete').click(); await tick(); await tick();"
        " return [S.localUploads.length, rows().some(r => r[1] === '202.fcs'), $('#toast').textContent];"
    )
    assert got == [0, False, "Deleted 202.fcs."]
