"""DECISIONS 310: the web app's one clear path. The "Önce bunları kontrol edin" form (a name is required and said
beside the field, what was seen is optional, a save moves the item to Checked, Undo takes the entry out of review.json
and keeps it in "replaced"), the history list (date and time, mode, pages read, reading path, plain status, short
ID), time estimates from recent runs, the results' summary from the team report's own data, Turkish by default.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from maya_audit_web import strings
from maya_audit_web.team_report import build_data
from maya_audit_web.runner import REPORT_JSON
from test_web_app import API, audit_of, web  # noqa: F401  (fixture)

STATIC = Path(__file__).resolve().parents[1] / "maya_audit_web" / "static"


@pytest.fixture
def finished(web):  # noqa: F811
    client = web()
    audit = audit_of(client)
    assert audit["state"] == "finished"
    return client, audit, client.app.state.runner.artifacts(audit["id"])


def _pending(client, audit):
    rows = client.get(f"{API}/audits/{audit['id']}/review").json()["confirm"]
    if not rows:
        pytest.skip("the demo audit has nothing to confirm")
    return rows[0]


# ---------------------------------------------------------------- the confirm form through the real routes

def test_a_check_without_a_name_is_refused_in_plain_words_beside_the_field(finished):
    client, audit, folder = finished
    row = _pending(client, audit)
    base = f"{API}/audits/{audit['id']}/review"
    for by in (None, "", "   "):
        refused = client.post(base, json={"finding_id": row["finding_id"], "result": "confirmed", "by": by})
        assert refused.status_code == 422, refused.text
        error = refused.json()["error"]
        assert error["code"] == "invalid_review" and error["details"]["fields"] == {"by": "Please enter your name."}
    client.cookies.set("maya_language", "tr")
    refused = client.post(base, json={"finding_id": row["finding_id"], "result": "rejected"})
    assert refused.json()["error"]["details"]["fields"]["by"] == "Lütfen adınızı yazın."
    assert not (folder / "review.json").exists()  # nothing was written


def test_a_check_needs_only_a_name_and_undo_takes_it_out_keeping_its_history(finished):
    client, audit, folder = finished
    row = _pending(client, audit)
    base = f"{API}/audits/{audit['id']}/review"
    saved = client.post(base, json={"finding_id": row["finding_id"], "result": "confirmed", "by": "Ayşe"})
    assert saved.status_code == 200, saved.text
    body = saved.json()
    entries = json.loads((folder / "review.json").read_text(encoding="utf-8"))["entries"]
    assert {e["finding_id"] for e in entries} == set(body["saved"]["finding_ids"]) >= set(row["finding_ids"])
    assert all(e["by"] == "Ayşe" and "seen" not in e for e in entries)  # what was seen is optional
    assert row["finding_id"] in [r["finding_id"] for r in body["reviewed"]]
    assert row["finding_id"] not in [r["finding_id"] for r in body["confirm"]]
    # Undo: the entries leave review.json, kept in "replaced"; the finding waits for a check again.
    undone = client.delete(f"{base}/{row['finding_id']}")
    assert undone.status_code == 200, undone.text
    after = json.loads((folder / "review.json").read_text(encoding="utf-8"))
    assert after["entries"] == [] and {e["finding_id"] for e in after["replaced"]} == set(body["saved"]["finding_ids"])
    assert all(e.get("undone") for e in after["replaced"])
    assert row["finding_id"] in [r["finding_id"] for r in undone.json()["confirm"]]
    assert undone.json()["reviewed"] == []
    again = client.delete(f"{base}/{row['finding_id']}")
    assert again.status_code == 404 and again.json()["error"]["code"] == "review_not_found"


def test_a_rejection_with_what_was_seen_and_a_card_note_is_kept_as_written(finished):
    client, audit, folder = finished
    row = _pending(client, audit)
    client.post(f"{API}/audits/{audit['id']}/review", json={"finding_id": row["finding_id"], "result": "rejected", "by": "Ayşe",
                                                             "seen": "  the menu is fine  ", "note": "not on the page"})
    entry = json.loads((folder / "review.json").read_text(encoding="utf-8"))["entries"][0]
    assert (entry["result"], entry["seen"], entry["note"]) == ("rejected", "the menu is fine", "not on the page")


# ---------------------------------------------------------------- the history list

def test_the_history_list_shows_site_date_mode_pages_path_status_and_short_id(finished):
    client, audit, folder = finished
    row = next(a for a in client.get(f"{API}/audits").json()["audits"] if a["id"] == audit["id"])
    assert row["host"] and row["created_at"] and row["mode_label"] and row["short_id"] == audit["id"][:8]
    assert row["path_label"] == "Maya" and row["pages_read"] >= 1
    assert row["status"] in ("finished", "page_cap", "too_few") and row["status_label"] == strings.t(f"history.status.{row['status']}")
    # Too few pages read: a plain status, whatever the engine's outcome.
    index = folder / "evidence" / "index.json"
    index.parent.mkdir(exist_ok=True)
    index.write_text(json.dumps({"pages": [{"url": "https://demo-shop.localhost/", "status": 200}]}), encoding="utf-8")
    row = next(a for a in client.get(f"{API}/audits").json()["audits"] if a["id"] == audit["id"])
    assert row["pages_read"] == 1 and row["status"] == "too_few" and row["status_label"] == "Too few pages read"
    client.cookies.set("maya_language", "tr")
    row = next(a for a in client.get(f"{API}/audits").json()["audits"] if a["id"] == audit["id"])
    assert row["status_label"] == "Çok az sayfa okundu"
    # Search by site.
    assert [a["id"] for a in client.get(f"{API}/audits", params={"q": "demo-shop"}).json()["audits"]] == [audit["id"]]
    assert client.get(f"{API}/audits", params={"q": "elsewhere.example"}).json()["audits"] == []


# ---------------------------------------------------------------- time from recent runs

def test_time_estimates_come_from_recent_runs_and_fall_back_to_a_range(finished):
    client, audit, _ = finished
    modes = {m["id"]: m["typical"] for m in client.get(f"{API}/settings").json()["modes"]}
    mine = modes[audit["mode"]]
    assert mine["known"] and mine["runs"] == 1 and mine["label"].startswith("about ")
    others = [m for mode, m in modes.items() if mode != audit["mode"]]
    assert others and all(not m["known"] and m["low_minutes"] <= m["high_minutes"] and "–" in m["label"] for m in others)
    client.cookies.set("maya_language", "tr")
    tr = {m["id"]: m["typical"] for m in client.get(f"{API}/settings").json()["modes"]}
    assert tr[audit["mode"]]["label"].startswith("yaklaşık ") and "dk" in tr[audit["mode"]]["label"]


# ---------------------------------------------------------------- the summary is the team report's

def test_the_results_summary_and_what_to_fix_are_the_team_reports_own(finished):
    client, audit, folder = finished
    view = client.get(f"{API}/audits/{audit['id']}/summary").json()
    assert view["overview_url"].endswith(f"/audits/{audit['id']}/overview")
    got = client.get(f"{API}/audits/{audit['id']}/overview", params={"lang": "tr"}).json()
    assert got["available"], got
    data = build_data.build_from_files(folder / REPORT_JSON, "tr", review=folder / "review.json")[0]
    assert got["headline"] == data["assessment"]["headline"]
    assert [k["value"] for k in got["kpis"][:3]] == [k["value"] for k in data["kpis"][:3]]
    assert got["kpis"][3]["value"] == str(len(data["confirm"]) + data["confirm_more"])
    assert [f["title"] for f in got["fixes"]] == [t["title"] for t in data["todos"] if t["severity"] != "Info"]
    assert all(f["owner"] and f["effort"] for f in got["fixes"])
    en = client.get(f"{API}/audits/{audit['id']}/overview", params={"lang": "en"}).json()
    assert en["headline"] == build_data.build_from_files(folder / REPORT_JSON, "en", review=folder / "review.json")[0]["assessment"]["headline"]


def test_the_app_starts_in_turkish_unless_the_reader_chose_english(tmp_path):
    from fastapi.testclient import TestClient
    from maya_audit_web.app import create_app
    from test_web_app import BASE
    client = TestClient(create_app(tmp_path / "web", port=8770, default_language="tr"), base_url=BASE)
    with client:
        client.get("/")
        assert client.get(f"{API}/settings").json()["language"] == "tr"
        client.cookies.set("maya_language", "en")
        assert client.get(f"{API}/settings").json()["language"] == "en"
    import maya_audit_web.__main__ as main
    assert 'default_language="tr"' in Path(main.__file__).read_text(encoding="utf-8")


# ---------------------------------------------------------------- the form in a browser

def _browser():
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    try:
        with sync_playwright() as pw:
            pw.chromium.launch().close()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"headless Chromium unavailable: {exc}")
    return sync_playwright


REVIEW = {
    "confirm": [{"finding_id": f"STR-{n}-0000000{n}", "finding_ids": [f"STR-{n}-0000000{n}"], "title": f"Finding {n}",
                 "severity": sev, "severity_label": sev, "reason": "unverified_check", "reason_label": "new check",
                 "placement": "confirm", "manual": None, "addresses": 3}
                for n, sev in enumerate(["S4", "S3", "S4", "Info", "S3"], 1)],
    "reviewed": [], "entries": []}


def _page(pw, lang="tr"):
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    shell = "<!doctype html><div id='notice' hidden></div><input id='search'><nav id='history'></nav><main id='result'></main>"
    # A page of its own origin (localStorage needs one); every other request is refused: nothing leaves the machine.
    page.route("**/*", lambda route: route.fulfill(status=200, content_type="text/html", body=shell)
               if route.request.url == "http://maya.test/" else route.abort())
    page.goto("http://maya.test/")
    page.add_script_tag(content=(STATIC / "app.js").read_text(encoding="utf-8").removesuffix("boot();\n"))
    page.evaluate("values => { state.strings = values; state.language = 'tr'; }", strings.table(lang))
    return browser, page, errors


def test_the_check_first_form_validates_saves_and_undoes_in_the_browser():
    sync_playwright = _browser()
    with sync_playwright() as pw:
        browser, page, errors = _page(pw)
        page.evaluate("""review => {
            window.calls = [];
            let data = JSON.parse(JSON.stringify(review));
            localStorage.removeItem('maya.reviewer');
            api = async (method, path, body) => {
                window.calls.push([method, path, body || null]);
                if (method === 'GET') return data;
                if (method === 'POST') {
                    const row = data.confirm.find(r => r.finding_id === body.finding_id);
                    data.confirm = data.confirm.filter(r => r !== row);
                    data.reviewed = [Object.assign({}, row, { manual: { result: body.result, by: body.by, date: '2026-11-05', note: body.note } })];
                    return Object.assign({}, data, { saved: { finding_ids: row.finding_ids } });
                }
                if (method === 'DELETE') { data.confirm = review.confirm; data.reviewed = []; return data; }
            };
            const box = document.createElement('section'); box.id = 'checks'; document.querySelector('#result').append(box);
            return showReview(box, 'abc');
        }""", REVIEW)
        box = page.locator("#checks")
        # At most three items, highest severity first; the rest one click away; the optional line is there.
        items = box.locator(":scope > ul.check-list > li.check-item")
        assert items.count() == 3
        assert [items.nth(i).locator(".sev").inner_text() for i in range(3)] == ["S3", "S3", "S4"]
        assert "Diğer 2 bulguyu göster" in box.inner_text()
        assert "İsteğe bağlı: kontrol etmezseniz bu bulgular rapora girmez, ekte kalır." in box.inner_text()
        first = items.nth(0)
        # No name: the message is beside the field, nothing is sent, no error bar.
        first.locator("button.ok").click()
        error = first.locator(".field-error").first
        assert error.is_visible() and error.inner_text() == "Lütfen adınızı yazın."
        assert page.evaluate("window.calls.filter(c => c[0] === 'POST').length") == 0
        assert page.locator("#notice").is_hidden()
        assert page.evaluate("document.activeElement.autocomplete") == "name"
        # Name given, "what you saw" left empty: saved; the item moves to Checked with an Undo.
        first.locator("input[autocomplete=name]").fill("Ayşe")
        first.locator("button.ok").click()
        page.wait_for_selector("#checks .checked-item.just")
        post = page.evaluate("window.calls.find(c => c[0] === 'POST')")
        assert post[2]["by"] == "Ayşe" and post[2]["result"] == "confirmed" and post[2]["seen"] is None
        assert page.evaluate("localStorage.getItem('maya.reviewer')") == "Ayşe"
        checked = box.locator(".checked-item.just")
        assert "Doğru" in checked.inner_text() and "Ayşe" in checked.inner_text()
        # The name is asked once: the next items say who will be saved instead of asking again.
        assert "Ayşe olarak kaydedilecek" in box.locator("li.check-item").first.inner_text()
        assert box.locator("li.check-item").first.locator("input[autocomplete=name]").is_hidden()
        checked.get_by_role("button", name="Geri al: Finding 2").click()
        page.wait_for_function("window.calls.some(c => c[0] === 'DELETE')")
        assert page.evaluate("window.calls.find(c => c[0] === 'DELETE')[1]") == "/audits/abc/review/STR-2-00000002"
        page.wait_for_function("!document.querySelector('#checks .checked-item')")
        assert errors == []
        browser.close()


def test_the_history_list_and_the_results_order_in_the_browser():
    sync_playwright = _browser()
    with sync_playwright() as pw:
        browser, page, errors = _page(pw)
        page.evaluate("""() => {
            api = async (method, path) => {
                if (path.startsWith('/audits?')) return { total: 1, audits: [{ id: 'b3198942aaaa', host: 'nihan.com.tr', state: 'finished',
                    created_at: '2026-10-30T07:17:59+00:00', mode_label: 'Standart 500', pages_read: 500, path_label: 'Maya ve Firecrawl',
                    status: 'page_cap', status_label: 'Sayfa sınırına ulaşıldı', short_id: 'b3198942' }] };
                if (path === '/analyses') return { analyses: [{ id: 'analysis-x', label: 'adile · r11', processed_at: '2026-10-21T10:00:00+00:00' }] };
                throw new Error('offline');
            };
            return loadHistory();
        }""")
        text = page.locator("#history").inner_text()
        for part in ("nihan.com.tr", "Standart 500", "500 sayfa okundu", "Maya ve Firecrawl", "Sayfa sınırına ulaşıldı", "b3198942",
                     "adile · r11"):
            assert part in text, part
        # The revised analyses are a section of their own below the audits, one row each (they used to overlap).
        boxes = page.evaluate("""() => Array.from(document.querySelectorAll('#history .history-open')).map(b => b.getBoundingClientRect())
                                   .map(r => [r.top, r.bottom])""")
        assert all(a[1] <= b[0] + 1 for a, b in zip(boxes, boxes[1:]))
        # The results page: summary, what to fix, check first, downloads, then the technical details, folded.
        page.evaluate("""() => {
            api = async (method, path) => {
                if (path.endsWith('/overview?lang=tr')) return { available: true, headline: 'Sorunlar düşük önemde.', kpis: [
                    { label: 'Kayıtlı sorun', value: '3', sub: '3 düşük' }, { label: 'Okunan sayfa', value: '50', sub: '' },
                    { label: 'Orta ve üstü sorunlu sayfa', value: '0', of: '50', sub: '' }, { label: 'Teyit bekleyen', value: '1', sub: '' }],
                    fixes: [{ n: 1, title: 'İç bağlantıları kanonik adrese yönlendirin', why: 'Neden', scope: '4 sayfa', severity: 'S4',
                              severity_label: 'Düşük', owner: 'Geliştirici', effort: 'Küçük', finding_ids: ['IDX-6-1'] }],
                    notes: 0, waiting: 1, confirm_scopes: {} };
                if (path.endsWith('/review')) return { confirm: [], reviewed: [], entries: [] };
                throw new Error('offline');
            };
            const view = { audit: { id: 'a1', project_id: 'nihan.com.tr' }, follow_ups: ['Eylem planını göster'],
                           team_report: { prepare: '/p', pdf: '/d', xlsx: '/x', default_lang: 'tr' } };
            document.querySelector('#result').append(resultView(view, {}));
        }""")
        page.wait_for_selector(".summary .verdict")
        labels = page.locator(".section-label").all_inner_texts()
        assert [label.split("·")[0].strip() for label in labels] == ["1", "2", "3", "4"]
        assert page.locator(".tech-details").evaluate("d => d.open") is False
        assert page.locator(".fix .hint").count() == 1  # "kanonik" has its "?" hint
        page.locator(".fix .hint").click()
        assert "Kanonik adres" in page.locator(".fix .hint-tip").inner_text()
        assert page.locator(".dl-card.off").inner_text().startswith("Müşteri özeti")
        order = page.evaluate("""() => ['.summary', '.fixes', '.review-list', '.downloads', '.followups', '.tech-details']
            .map(s => document.querySelector(s).getBoundingClientRect().top)""")
        assert order == sorted(order)
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
        assert errors == []
        browser.close()
