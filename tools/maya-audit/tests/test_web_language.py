"""The Turkish interface: every sentence present with its placeholders, the switch, and what stays English."""
import json
import re

import pytest

pytest.importorskip("fastapi")

from maya_audit_web import catalog, strings  # noqa: E402
from test_web_app import API, Site, cloudflare, error, get, plan, start, web  # noqa: E402,F401

# A placeholder by name, whatever form it takes: "{count}" and "{count:page|pages}" are both `count`.
HOLES = re.compile(r"\{(\w+)(?::[^{}]*)?\}")


def test_turkish_has_every_sentence_with_the_same_placeholders():
    english, turkish = strings.STRINGS["en"], strings.STRINGS["tr"]
    assert set(turkish) == set(english)
    assert [key for key in english if sorted(HOLES.findall(english[key])) != sorted(HOLES.findall(turkish[key]))] == []
    assert [key for key, value in turkish.items() if not value.strip()] == []
    same = [key for key in english if english[key] == turkish[key] and len(english[key]) > 12]
    # Only pure layouts and product names may be identical in both languages.
    assert same == ["detail.brand_name", "detail.duplicate_group", "practical.merged", "follow.item", "follow.check.lead", "follow.coverage.item", "pdf.source.search_console", "pdf.source.bing"], same
    raw = json.loads((strings.LOCALES / "tr.json").read_text(encoding="utf-8"))
    assert set(raw) == set(english)  # nothing in the file is silently dropped
    assert set(catalog.TRANSLATIONS["tr"]) == set(catalog.all_whys())  # and every "why it can matter" note


def test_english_stays_the_default_and_an_unknown_language_means_english():
    assert strings.current_language() == "en" and strings.t("nav.new") == "New audit"
    assert strings.t("nav.new", "tr") == "Yeni denetim" and strings.t("nav.new", "xx") == "New audit"
    assert strings.t("fc.amount.credits", "tr", credits=6) == "en fazla 6 kredi"
    assert catalog.note("ACC-9")["why"].startswith("When a site's protection")


def test_the_switch_changes_the_interface_the_reports_own_text_stays_english_and_the_shown_title_is_turkish(web, tmp_path):
    client = web(site=Site(respond=cloudflare))
    session = client.get(f"{API}/session").json()
    assert session["language"] == "en" and [item["id"] for item in session["languages"]] == ["en", "tr"]
    assert "ana dili Türkçe olan biri" in next(item["note"] for item in session["languages"] if item["id"] == "tr")
    english = start(client, plan(client))
    error(client.put(f"{API}/session/language", json={"language": "xx"}), 422, "unknown_language")
    chosen = client.put(f"{API}/session/language", json={"language": "tr"})
    assert chosen.status_code == 200 and "maya_language=tr" in chosen.headers["set-cookie"]
    assert client.get(f"{API}/session").json()["language"] == "tr"
    table = client.get(f"{API}/strings").json()
    assert table["language"] == "tr" and table["strings"]["nav.new"] == "Yeni denetim" and set(table["strings"]) == set(strings.STRINGS["en"])
    assert client.get(f"{API}/strings", params={"language": "en"}).json()["strings"]["nav.new"] == "New audit"
    assert [mode["label"] for mode in client.get(f"{API}/settings").json()["modes"]] == ["Tek sayfa", "Hızlı ~50", "Akıllı ~150", "Derin ~500", "Özel sayı"]  # DECISIONS 327, 331

    view = get(client, english, "/summary")  # an audit made in English, read in Turkish
    assert view["blocked"]["headline"].startswith("Site bu denetimi engelledi") and view["pages_stat"]["label"] == "Okunabilen sayfalar"
    assert view["outcome"]["label"] == "Site düzgün okunamadı" and view["technical"]["title"] == "Teknik ayrıntılar"
    row = next(row for row in get(client, english, "/findings", limit=100)["items"] if row["check_id"] == "ACC-9")
    assert row["severity_label"] in ("Orta", "Düşük") and row["why"].startswith("Bir sitenin koruması")
    report = client.get(f"{API}/audits/{english['id']}/result").json()
    # The report's own words stay English; what the reader is shown is Turkish, with the numbers and names kept.
    assert row["title"] in [f["title"] for check in report["checks"] for f in check["findings"]] and row["title"].startswith("Maya's crawler blocked by bot protection")
    assert row["title_shown"].startswith("Maya'nın tarayıcısı bot korumasına takıldı") and "Cloudflare" in row["title_shown"] and row["untranslated"] is False
    assert row["fix_shown"].startswith("Cloudflare bot ayarlarında") and "(İngilizce)" not in row["title_shown"] + row["fix_shown"] + row["expected_shown"]
    assert row["fix"].startswith("In the bot settings of Cloudflare") and row["expected"] == "a crawler that identifies itself honestly receives the page"
    # The printed report is written in the audit's language (C61): Turkish only when asked for explicitly.
    assert "Okunabilen sayfalar" in client.get(f"{API}/audits/{english['id']}/print?full=true&lang=tr").text
    assert "Readable pages" in client.get(f"{API}/audits/{english['id']}/print?full=true").text
    made = plan(client)
    assert made["mode_label"] == "Hızlı ~50" and "robots.txt" in " ".join(made["limitations"] + made["included"])
    turkish = start(client, made)
    log = client.get(f"{API}/audits/{turkish['id']}/events", headers={"last-event-id": "0"}).text
    assert "Sayfalar okunuyor" in log and "Reading pages" not in log  # the worker writes in the audit's language
    assert turkish["state_label"] == "Tamamlandı"

    client.put(f"{API}/session/language", json={"language": "en"})
    assert get(client, english, "/summary")["pages_stat"]["label"] == "Readable pages" and strings.current_language() == "en"
