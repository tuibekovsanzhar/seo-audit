"""DECISIONS 276: what the maya-audit-pro skill says about the engine ("Motorun bilinen tuzakları" in its SKILL.md) is
checked against the engine, so a skill sentence cannot go stale silently. Found the first time: the skill told the
model to write "not confirmed by another client" for the one IDX-1 state that a browser had confirmed."""
import json
import re
import sys
from pathlib import Path

import httpx

from test_brand_and_launch_gate import no_lookups  # noqa: F401
from test_false_alarms import HTML_TYPE, KAFE, answer, audited

SKILL = Path(__file__).resolve().parents[1] / ".agents" / "skills" / "maya-audit-pro"
sys.path.insert(0, str(SKILL / "scripts"))
sys.path.insert(0, str(SKILL / "tests"))
import build_data  # noqa: E402
import render  # noqa: E402
from test_export_compat import Wording  # noqa: E402

EMPTY = httpx.Response(200, headers=HTML_TYPE, content=b"")
OK = answer(title="Ürün | Demo Kafe")
TRAPS = SKILL.joinpath("SKILL.md").read_text(encoding="utf-8").split("## Motorun bilinen tuzakları", 1)[1].split("\n## ", 1)[0]


def strengths(browser_answer):
    """An empty page asked three times: the crawl, the IDX-1 refetch, then (third) as a browser."""
    routes = {"/": answer(title="Demo Kafe", body='<a href="/urun/1">u</a>'),
              "/urun/1": lambda n: EMPTY if n < 3 else browser_answer}
    outcome = audited(routes, sitemap=["/", "/urun/1"], probes_enabled=True)
    empty = [f for f in outcome.by_id["IDX-1"].findings if "empty" in f.title]
    return {f.evidence["observation_strength"] for f in empty}


def builder(lang="tr"):
    r = {"checks": [], "findings_in_priority_order": [], "problem_summary": {}, "crawl": {"origin": KAFE, "pages": []},
         "audit_status": {}}
    return build_data.Builder(r, lang, render.LABELS[lang], json.loads((build_data.REFS / "sahip_efor.json").read_text()),
                              Wording(), None, "test", False, None)


def test_repeated_empty_means_a_browser_got_an_empty_page_too(no_lookups):
    assert strengths(EMPTY) == {"repeated_empty"}
    assert strengths(OK) == {"repeated_empty_to_maya_content_to_a_browser"}


def test_the_skill_says_repeated_measurement_only_for_the_browser_confirmed_state():
    b = builder()
    confirmed = {"confidence": "verified", "evidence": {"observation_strength": "repeated_empty"}}
    same_client = {"confidence": "verified", "evidence": {"observation_strength": "repeated_empty_same_client_only"}}
    assert b.status_text(confirmed) == render.LABELS["tr"]["repeated"]
    assert b.status_text(same_client) != render.LABELS["tr"]["repeated"]
    bullet = next(line for line in TRAPS.split("\n- ") if line.startswith("**IDX-1"))
    confirmed_line = next(line for line in bullet.splitlines() if "`repeated_empty`:" in line)
    assert "doğrulanmıştır" in confirmed_line and "**demez**" in confirmed_line


def test_every_empty_page_state_the_engine_writes_is_explained_in_the_skill():
    source = (Path(__file__).resolve().parents[1] / "maya_audit" / "checks" / "index.py").read_text(encoding="utf-8")
    # The values written to evidence.observation_strength: the IDX-1 empty-page states, not other keys of the same stem.
    block = source.split("strength = (", 1)[1].split("findings.append", 1)[0]
    states = set(re.findall(r'"(repeated_empty[a-z_]*)"', block)) | set(
        re.findall(r'"observation_strength": "(repeated_empty[a-z_]*)"', source))
    assert states >= {"repeated_empty", "repeated_empty_same_client_only", "repeated_empty_mixed_browser_sample",
                      "repeated_empty_to_maya_content_to_a_browser"}
    assert [s for s in sorted(states) if f"`{s}`" not in TRAPS] == []


def test_idx5_uses_the_ratio_in_its_title_not_scope_count():
    # Every title form the engine writes (checks/index.py, then judgments.py). Found stale here: the skill matched only
    # an older form, so the KPI and the table fell back to the narrowed scope count.
    for title in ("123 of 245 sitemap URL(s) (50%) are not live, indexable pages",
                  "123 of 245 sitemap URL(s) checked (50%) are not live, indexable pages; 9 more were not checked",
                  "123 sitemap URL observation(s) require differentiated review (245 checked); 49 already have IDX-1 "
                  "retrieval evidence"):
        finding = {"id": "IDX-5-x", "check_id": "IDX-5", "severity": "S3", "confidence": "verified", "title": title,
                   "evidence": {}, "scope": {"kind": "sitewide", "count": 57, "urls": []}}
        b = builder()
        b.ordered = [finding]
        assert b.sitemap_ratio()[:2] == (123, 245), title
    assert "IDX-5" in TRAPS and "başlıktaki oranı" in TRAPS
