"""--save-evidence: what each page said, kept so a finding can be checked later without crawling again."""

import json
from dataclasses import replace

import pytest

from fakeserver import FakeServer, Response, Site
from maya_audit import audit as audit_module
from maya_audit import cli, evidence_store
from maya_audit.config import CrawlConfig
from test_answer_key import BLOG_TEMPLATE, ld
from test_deadline_hosted_hardening import QUIET
from test_review_fixes import TR, links, page


@pytest.fixture
def site(monkeypatch):
    """A fake site behind the real CLI; the audit is the real one with the waits shortened."""
    routes = {"/robots.txt": Response(body="User-agent: *\nAllow: /\n", content_type="text/plain"),
              "/": page(f"<h1>Ana</h1><p>{TR}</p>" + links(["/tr/yazi/", "/tr/eski/", "/tr/diger/"])),
              "/tr/yazi/": page(f"<h1>Çocuklarda Dikkat Eksikliği</h1><h2>Belirtiler</h2><p>{TR}</p><p>Süre 6 aydır ‹teyit›.</p>",
                                head=ld(BLOG_TEMPLATE) + '<meta property="article:published_time" content="{{publishDate}}">'
                                     '<meta property="og:title" content="Dikkat Eksikliği"><meta name="description" content="Kısa açıklama">',
                                nav='<a href="/">MENÜ METNİ</a>', footer="ALT BİLGİ METNİ"),
              "/tr/eski/": Response(301, "", headers={"Location": "/tr/yeni/"}),
              "/tr/yeni/": page(f"<h1>Yeni adres</h1><p>{TR}</p>"),
              "/tr/diger/": page(f"<h1>Diğer</h1><p>{TR}</p>")}
    server = FakeServer(Site(routes))
    server.__enter__()
    real = audit_module.run_audit
    monkeypatch.setattr(cli, "run_audit", lambda url, config: real(url, replace(config, **QUIET)))
    yield server
    server.__exit__(None, None, None)


def files(folder):
    index = json.loads((folder / "index.json").read_text(encoding="utf-8"))
    return index, {entry["url"].split("/", 3)[3]: json.loads((folder / entry["file"]).read_text(encoding="utf-8")) for entry in index["pages"]}


def test_key_pages_are_saved_by_default_next_to_the_json_report(site, capsys, tmp_path):
    report = tmp_path / "audit.json"
    code = cli.main(["crawl", site.base_url + "/", "--key-page", "/tr/yazi/", "--key-page", "/tr/eski/", "--json", str(report)])
    assert code in (0, 3)
    folder = tmp_path / "audit-evidence"
    index, saved = files(folder)
    assert set(saved) == {"tr/yazi/", "tr/eski/", "tr/yeni/"}  # the key pages, and where one of them redirected to
    assert index["mode"] == "key" and index["total_bytes"] == sum(entry["bytes"] for entry in index["pages"])

    yazi = saved["tr/yazi/"]
    assert yazi["title"] == "Sayfa" and yazi["status"] == 200 and yazi["html_lang"] == "tr"
    assert yazi["headings"] == [{"level": 1, "text": "Çocuklarda Dikkat Eksikliği"}, {"level": 2, "text": "Belirtiler"}]
    assert {"property": "article:published_time", "content": "{{publishDate}}"} in yazi["meta_properties"]
    assert {"property": "og:title", "content": "Dikkat Eksikliği"} in yazi["meta_properties"]
    assert {"name": "description", "content": "Kısa açıklama"} in yazi["meta"]
    [block] = yazi["json_ld_blocks"]
    assert json.loads(block)["author"]["name"] == "{{author_name}}"  # the block as written, slots and all
    assert "Süre 6 aydır ‹teyit›." in yazi["main_text"] and "Çocuklarda Dikkat Eksikliği" in yazi["main_text"]
    assert "MENÜ METNİ" not in yazi["main_text"] and "ALT BİLGİ METNİ" not in yazi["main_text"]  # main text only
    assert saved["tr/eski/"]["status"] == 301 and saved["tr/eski/"]["redirect_location"].endswith("/tr/yeni/")

    saved_note = json.loads(report.read_text(encoding="utf-8"))["evidence_saved"]
    assert saved_note["pages"] == 3 and saved_note["folder"] == "audit-evidence" and saved_note["mode"] == "key"
    assert f"verification evidence for 3 page(s) saved to {folder}" in capsys.readouterr().out


def test_without_key_pages_nothing_is_saved_and_all_or_none_can_be_asked_for(site, capsys, tmp_path):
    assert cli.main(["crawl", site.base_url + "/", "--json", str(tmp_path / "a.json")]) in (0, 3)
    assert not (tmp_path / "a-evidence").exists() and "evidence_saved" not in json.loads((tmp_path / "a.json").read_text(encoding="utf-8"))
    assert "verification evidence" not in capsys.readouterr().out

    folder = tmp_path / "everything"
    assert cli.main(["crawl", site.base_url + "/", "--save-evidence", "all", "--evidence-dir", str(folder)]) in (0, 3)
    index, saved = files(folder)
    assert set(saved) == {"", "tr/yazi/", "tr/eski/", "tr/yeni/", "tr/diger/"}
    assert [entry["file"] for entry in index["pages"]][0] == "001-home.json"

    assert cli.main(["crawl", site.base_url + "/", "--key-page", "/tr/yazi/", "--save-evidence", "none",
                     "--json", str(tmp_path / "n.json")]) in (0, 3)
    assert not (tmp_path / "n-evidence").exists()


def test_an_evidence_folder_already_in_use_is_refused_before_the_crawl(site, capsys, tmp_path, monkeypatch):
    folder = tmp_path / "used"
    folder.mkdir()
    (folder / "old.json").write_text("{}")
    monkeypatch.setattr(cli, "run_audit", lambda *a, **k: pytest.fail("the audit must not start"))
    argv = ["crawl", site.base_url + "/", "--key-page", "/tr/yazi/", "--evidence-dir", str(folder)]
    assert cli.main(argv) == 2 and "evidence folder already holds files" in capsys.readouterr().err


def test_sizes_are_capped_per_page_and_per_audit(site, tmp_path, monkeypatch):
    monkeypatch.setattr(evidence_store, "EVIDENCE_MAX_TEXT_CHARS", 120)
    monkeypatch.setattr(evidence_store, "EVIDENCE_MAX_JSONLD_CHARS", 50)
    folder = tmp_path / "small"
    cli.main(["crawl", site.base_url + "/", "--save-evidence", "all", "--evidence-dir", str(folder)])
    index, saved = files(folder)
    yazi = saved["tr/yazi/"]
    assert len(yazi["main_text"]) == 120 and yazi["main_text_truncated"] is True
    assert sum(len(b) for b in yazi["json_ld_blocks"]) == 50 and yazi["json_ld_truncated"] is True

    monkeypatch.setattr(evidence_store, "EVIDENCE_MAX_TOTAL_BYTES", index["pages"][0]["bytes"] + index["pages"][1]["bytes"] + 10)
    monkeypatch.setattr(evidence_store, "EVIDENCE_MAX_PAGES", 300)
    capped = tmp_path / "capped"
    cli.main(["crawl", site.base_url + "/", "--save-evidence", "all", "--evidence-dir", str(capped)])
    index, _ = files(capped)
    assert len(index["pages"]) == 2 and len(index["not_saved"]) == 3 and "size limit" in index["not_saved"][0]["reason"]
    assert index["total_bytes"] <= evidence_store.EVIDENCE_MAX_TOTAL_BYTES

    monkeypatch.setattr(evidence_store, "EVIDENCE_MAX_PAGES", 1)
    monkeypatch.setattr(evidence_store, "EVIDENCE_MAX_TOTAL_BYTES", 10**9)
    one = tmp_path / "one"
    cli.main(["crawl", site.base_url + "/", "--save-evidence", "all", "--evidence-dir", str(one)])
    index, _ = files(one)
    assert len(index["pages"]) == 1 and "page limit of 1" in index["not_saved"][0]["reason"]


def test_batch_can_save_evidence_per_brand_and_the_output_folder_is_git_ignored(site, tmp_path):
    import subprocess

    brands = tmp_path / "brands.csv"
    brands.write_text(f"name,url\nMarka,{site.base_url}/\n", encoding="utf-8")
    out = tmp_path / "batch"
    assert cli.main(["batch", str(brands), "--out", str(out), "--save-evidence", "all", "--delay", "0"]) == 0
    index, saved = files(out / "Marka-evidence")
    assert len(saved) == 5 and json.loads((out / "Marka.json").read_text(encoding="utf-8"))["evidence_saved"]["pages"] == 5
    assert cli.main(["batch", str(brands), "--out", str(out), "--save-evidence", "all", "--delay", "0"]) == 2  # no silent overwrite
    root = cli.Path(cli.__file__).resolve().parent.parent
    inside = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=root, capture_output=True, text=True)
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        # An unzipped copy has no Git history, so what .gitignore covers cannot be asked. Everything above still ran.
        pytest.skip("this folder is not a Git repository, so the .gitignore part of this test cannot run")
    assert subprocess.run(["git", "check-ignore", "-q", "output/evidence/example.com/index.json"], cwd=root).returncode == 0
    assert subprocess.run(["git", "check-ignore", "-q", "output/batch-x/Marka-evidence/index.json"], cwd=root).returncode == 0
    assert evidence_store.default_folder("https://www.example.com/x", None) == cli.Path("output/evidence/www.example.com")


def test_the_full_affected_address_lists_are_written_beside_the_json_report(site, capsys, tmp_path):
    # DECISIONS 259: report.json keeps 25 addresses a finding; a client report needs every one.
    report = tmp_path / "audit.json"
    assert cli.main(["crawl", site.base_url + "/", "--json", str(report)]) in (0, 3)
    companion = json.loads((tmp_path / "audit.affected-urls.json").read_text(encoding="utf-8"))
    saved = json.loads(report.read_text(encoding="utf-8"))
    ids = {f["id"]: f for c in saved["checks"] for f in c.get("findings") or []}
    assert companion and set(companion) <= set(ids) | {r["id"] for c in saved["checks"] for r in c.get("review_items") or []}
    for fid, urls in companion.items():
        if fid in ids:
            assert urls[:25] == list(ids[fid]["scope"].get("urls") or [])[:25] or not ids[fid]["scope"].get("urls")
    assert "full affected-address lists written to" in capsys.readouterr().out
