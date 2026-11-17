"""DECISIONS 354: report lines left in English in Turkish reports (the text check's RG-21 over the saved audits)."""
from __future__ import annotations

from maya_audit import page_measures, text_gate
from maya_audit_web import wording as w

READER = ("Cloudflare rate-limited Maya's direct crawler on 1 of 2 request(s). 148 page(s) were read through Firecrawl "
          "instead. Genuine AI-crawler access was not measured.")


def test_the_reader_line_of_kapsam_is_turkish_with_its_check():
    from maya_audit import client_appendix
    assert w.title("ACC-9", READER, "tr") == ("Cloudflare, Maya'nın doğrudan tarayıcısını 2 istekten 1 tanesinde hız sınırına "
                                               "taktı. Bunun yerine 148 sayfa Firecrawl üzerinden okundu. Gerçek yapay zekâ "
                                               "tarayıcısı erişimi ölçülmedi.", True)
    from maya_audit_web.team_report import build_data
    for module in (client_appendix, build_data):  # the Kapsam line is worded with its check id, never None
        assert "title(None," not in open(module.__file__, encoding="utf-8").read()


def test_older_saved_wordings_are_turkish_and_give_no_rule_id():
    cases = {
        "ACC-1": "robots.txt returned a server error or was unreachable on 2 of 3 fetches",
        "RND-4": "1 page(s) embed content in an iframe; its text is not part of the page",
        "ACC-9": ("Cloudflare challenged Maya's own crawler (an unverified bot). Verified search and AI crawlers are normally "
                  "not affected (not measured here); the site was read through Firecrawl."),
        "STR-14": ("Shared header/footer: link “Bağlantı” to /a has only generic text (on 119 page(s)) — link “Bağlantı” to /a "
                   "has only generic text (on 119 page(s)); https://x.test/a"),
    }
    for check, text in cases.items():
        shown, done = w.title(check, text, "tr")
        assert done and "(İngilizce)" not in shown and not text_gate.EN_WORDS.findall(text_gate._plain(shown))[1:], shown
        assert w.title_key(check, text) == [] or check == "STR-14"  # no new rule id
    assert "1 page embeds" in w.title("RND-4", cases["RND-4"], "en")[0]
    lines = ["moodist.com: host could not be resolved safely: moodist.com",
             "www.a.test: robots.txt for http://www.a.test is unavailable: robots.txt returned unexpected status 301 after "
             "redirects; treated as unreachable",
             "on another site; external link checks are off (--check-external-links)"]
    for line in lines:
        assert w.line(line, "tr")[1], line
    assert w.label("grids not checked for a form control beside them", "tr")[1]
    assert w.fix("Nothing needs fixing for this audit. To let Maya's own crawler read the site directly, allow its user "
                 "agent in the firewall or bot-protection rules. To see what named AI crawlers receive, verify ownership so "
                 "ACC-4 can test them.", "tr")[1]


def test_an_older_report_with_a_script_count_still_builds_its_page_measures():
    page = {"url": "https://x.test/", "status": 200, "analysis": {"external_scripts": 7, "visible_words": 10}}
    measured = page_measures.measure(page)
    assert "blocking_scripts" not in measured


def test_a_date_in_a_cards_status_is_not_a_number_to_check():
    card = {"n": 1, "finding_ids": ["F1"], "title": "Bağlantıları düzeltin", "status": "Elle teyit edildi (2026-11-05)",
            "all_urls": ["https://x.test/a"]}
    report = {"checks": [{"check_id": "IDX-6", "findings": [{"id": "F1", "rule_id": "idx6.broken", "evidence": {}}]}]}
    assert text_gate.check({"lang": "tr", "todos": [card]}, report) == []
