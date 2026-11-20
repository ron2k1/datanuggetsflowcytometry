"""The page and its caching, the Host check, the pinned CSP, the error shape, the scrubber and the
rounding, what the server never imports, the limits' per-minute window and the workspace's record
kinds. Health and config are tested in features/meta."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from dnapp.core.config import LOCAL_CAPS, TRIAL_CAPS, Settings
from dnapp.core.errors import ApiError, Scrubber
from dnapp.core.http import CSP, safe_csv
from dnapp.core.limits import MINUTE_S, Limits
from dnapp.core.payload import q, r4
from dnapp.core.workspace import META, Workspaces
from testkit import API, assert_error, make_settings, upload

SERVER = Path(__file__).resolve().parents[1] / "server" / "dnapp"


def test_the_page_and_its_modules_are_revalidated(make_client, tmp_path):
    c = make_client()
    js = tmp_path / "a" / "web" / "js"
    js.mkdir(parents=True)
    (js / "main.js").write_text("export const a = 1;\n", encoding="utf-8")
    page, module = c.get("/"), c.get("/js/main.js")
    for r in (page, module):
        assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"
    again = c.get("/js/main.js", headers={"if-none-match": module.headers["etag"]})
    assert again.status_code == 304 and again.headers["cache-control"] == "no-cache"
    assert "cache-control" not in c.get(f"{API}/health").headers


LOOPBACK = ["127.0.0.1", "127.0.0.1:8000", "localhost", "localhost:8000", "[::1]", "[::1]:8000"]
FOREIGN = ["evil.example", "evil.example:8000", "192.168.1.20:8000", "[::2]:8000",
           "localhost.evil.example", "127.0.0.1.evil.example:8000", "[::1", "localhost:x"]  # fmt: skip


@pytest.mark.parametrize("host", LOOPBACK)
def test_local_mode_answers_the_loopback_names(make_client, host):
    c = make_client(allowed_hosts=())
    assert c.get(f"{API}/health", headers={"host": host}).status_code == 200
    assert c.get("/", headers={"host": host}).status_code == 200


@pytest.mark.parametrize("host", FOREIGN)
def test_local_mode_refuses_every_other_host(make_client, fcs_202, host):
    """Local mode has no login, so a page on another site that resolves its name to this
    computer (DNS rebinding) must not reach the API or the page."""
    c = make_client(allowed_hosts=())
    for r in (
        c.get("/", headers={"host": host}),
        c.get(f"{API}/uploads", headers={"host": host}),
        upload(c, fcs_202, headers={"host": host}),
    ):
        assert_error(r, 400, "invalid_host", None)
        assert r.headers["x-content-type-options"] == "nosniff"
    assert c.get(f"{API}/uploads", headers={"host": "localhost:8000"}).json() == {"uploads": []}


def test_allowed_hosts_add_names_to_local_mode(make_client):
    c = make_client(allowed_hosts=("dn.lan", "[fe80::1]"))
    for host in ("dn.lan", "DN.LAN:8000", "[fe80::1]:8000", "127.0.0.1:8000"):
        assert c.get(f"{API}/health", headers={"host": host}).status_code == 200, host
    assert_error(c.get(f"{API}/health", headers={"host": "evil.example"}), 400, "invalid_host")
    anyhost = make_client(sub="any", allowed_hosts=("*",))
    assert anyhost.get(f"{API}/health", headers={"host": "evil.example"}).status_code == 200


def test_trial_mode_checks_hosts_only_when_they_are_listed(make_client):
    """The hosted trial sits behind a proxy whose name only its operator knows, so trial mode
    answers any host unless DN_ALLOWED_HOSTS names some. The loopback names stay allowed, so the
    image's health check (Host 127.0.0.1:8000) keeps passing."""
    free = make_client("trial", allowed_hosts=())
    assert free.get(f"{API}/health", headers={"host": "trial.example.org"}).status_code == 200
    listed = make_client("trial", sub="t", allowed_hosts=("trial.example.org",))
    for host in ("trial.example.org", "127.0.0.1:8000"):
        assert listed.get(f"{API}/health", headers={"host": host}).status_code == 200, host
    assert_error(listed.get(f"{API}/health", headers={"host": "evil.example"}), 400, "invalid_host")


def test_allowed_hosts_come_from_the_environment():
    env = {"DN_ALLOWED_HOSTS": " DN.lan , ,box:8000,[fe80::1]:8000 "}
    assert Settings.from_env(env).allowed_hosts == ("dn.lan", "box:8000", "[fe80::1]:8000")
    assert Settings.from_env({}).allowed_hosts == ()


@pytest.mark.parametrize("entry", ["dn lan", "http://dn.lan", "[::1", "box:port"])
def test_an_allowed_host_that_is_not_a_host_stops_the_start(make_client, tmp_path, entry):
    with pytest.raises(SystemExit, match="DN_ALLOWED_HOSTS"):
        make_client(allowed_hosts=(entry,))
    assert not (tmp_path / "a" / "data").exists()


def test_csp_is_exactly_the_pinned_one():
    assert CSP == (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' "
        "data: blob:; connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; "
        "frame-ancestors 'none'; form-action 'self'"
    )


def test_unknown_routes_use_the_error_shape(make_client):
    c = make_client()
    assert_error(c.get(f"{API}/nope"), 404, "not_found")
    assert_error(c.get(f"{API}/runs/r99"), 404, "not_found")
    assert_error(c.get(f"{API}/uploads/u9"), 404, "not_found")
    assert_error(c.get(f"{API}/jobs/j9"), 404, "not_found")
    assert_error(c.get(f"{API}/flow/gates/g9"), 404, "not_found")
    # general runs left the app; their route is now just an unknown one
    assert_error(c.post(f"{API}/runs/general", json={"upload": "u1"}), 404, "not_found")


def test_scrubber_leaves_names_only(tmp_path):
    root = tmp_path / "data"
    s = Scrubber([root])
    win = str(root / "ws" / "local" / "uploads" / "u1" / "202.fcs")
    assert s.text(f"{win} is missing") == "202.fcs is missing"
    assert s.text(f"'{root}' ok") == "'' ok"
    posix = str(root).replace("\\", "/") + "/ws/x/runs/r1"
    assert s.text(f"path: {posix}, done") == "path: r1, done"
    assert s.obj({"a": [win], "b": 1}) == {"a": ["202.fcs"], "b": 1}
    assert s.obj({win: {posix: 2}, 3: "x"}) == {"202.fcs": {"r1": 2}, 3: "x"}  # keys too


def test_rounding_and_csv_safety(tmp_path):
    assert r4(3.14159265) == 3.142 and r4(float("nan")) is None and r4(None) is None
    assert q([[1.23456, float("inf")]]) == [[1.235, None]]
    p = tmp_path / "x.csv"
    p.write_text("a,b\n=1+2,-1.5\n@x,+3\n-x,\tz\n", encoding="utf-8")
    text = safe_csv(p).decode()
    assert text == "a,b\n'=1+2,-1.5\n'@x,+3\n'-x,'\tz\n"


def test_csv_guard_keeps_signed_non_finite_numbers(tmp_path):
    """A6: a cell that reads as a float is a number, finite or not, and keeps its text: -inf as
    pandas writes it, -Infinity as JSON and JavaScript do, -nan as C's printf does. A formula
    stays prefixed even when it is made of numbers."""
    numbers = ["-inf", "-Infinity", "-nan", "+inf", "-1.5e-3"]
    formulas = ["-1+1", "=cmd", "+1-1", "-2*3", "@SUM(1)"]
    p = tmp_path / "x.csv"
    p.write_text("a\n" + "\n".join(numbers + formulas) + "\n", encoding="utf-8")
    cells = safe_csv(p).decode().splitlines()[1:]
    assert cells == numbers + ["'" + f for f in formulas]


def test_server_never_imports_pyplot_or_package_math():
    """S12: no pyplot anywhere in the server, and no clustering/PCA/t-SNE code of its own."""
    banned_imports = {"matplotlib.pyplot", "sklearn", "datanuggets.plot"}
    banned_names = {"wpca", "whclust", "cut_tree", "create_dn", "wkmeans", "TSNE"}
    for path in SERVER.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    assert a.name not in banned_imports, (path.name, a.name)
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module not in banned_imports, (path.name, node.module)
                for a in node.names:
                    assert a.name not in banned_names, (path.name, a.name)


def test_a_per_minute_window_counts_each_request(clock):
    """Live-cells counts are limited per address and minute. The window counts the requests it
    lets through, and a None limit counts nothing."""
    limit = TRIAL_CAPS.livecells_counts_per_ip_minute
    lim = Limits(TRIAL_CAPS, clock)
    for _ in range(limit):
        lim.take_per_minute("counts", "1.2.3.4", limit, "counts")
    clock.advance(10)
    with pytest.raises(ApiError) as e:
        lim.take_per_minute("counts", "1.2.3.4", limit, "counts")
    assert e.value.status == 429 and e.value.code == "rate_limited"
    assert e.value.headers["Retry-After"] == str(MINUTE_S - 10)
    assert "last minute" in e.value.message
    lim.take_per_minute("counts", "5.6.7.8", limit, "counts")  # per address
    lim.take_per_minute("other", "1.2.3.4", limit, "counts")  # and per kind of request
    clock.advance(MINUTE_S - 10)
    lim.take_per_minute("counts", "1.2.3.4", limit, "counts")
    local = Limits(LOCAL_CAPS, clock)
    for _ in range(limit + 1):
        local.take_per_minute("counts", "1.2.3.4", LOCAL_CAPS.livecells_counts_per_ip_minute, "x")
    assert not local.requests


def test_a_meta_json_from_before_livecells_reads_as_empty(tmp_path, clock):
    settings = make_settings(tmp_path)
    ws = Workspaces(settings, clock).local()
    assert ws.records("livecells") == {} and ws.next_id("livecells") == "l1"
    meta = json.loads((ws.path / META).read_text(encoding="utf-8"))
    del meta["livecells"]
    (ws.path / META).write_text(json.dumps(meta), encoding="utf-8")
    assert Workspaces(settings, clock).local().records("livecells") == {}
