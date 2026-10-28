"""Stage B contracts: synthetic sectors and evidence, never a benchmark-domain exception."""
import json
from types import SimpleNamespace as NS

import httpx
import pytest

from maya_audit import brand
from maya_audit.findings import Finding, Severity, Rationale, CheckResult, scope_for
from maya_audit.models import Confidence, to_jsonable
from test_false_alarms import audited


ORIGIN = "https://fieldwork.example"


def identity_site(*, typed=None, alternate=False, localized=False, conflicting=False):
    routes = {}
    for n, path in enumerate(("/", "/care", "/about")):
        name = "Coastline Health"
        if alternate and n == 1:
            name = "Coastline Medical"
        if localized and n == 1:
            name = "Kiyi Saglik"
        if conflicting and n == 1:
            name = "Unrelated Workshop"
        lang = "tr" if localized and n == 1 else "en"
        organization = {"@type": "Organization", "@id": ORIGIN + "/#organization", "url": ORIGIN,
                        "name": name}
        if alternate:
            organization["alternateName"] = ["Coastline Health", "Coastline Medical"]
        nodes = [{"@context": "https://schema.org", **organization},
                 {"@context": "https://schema.org", "@type": "WebSite", "@id": ORIGIN + "/#website",
                  "url": ORIGIN, "name": name, "inLanguage": lang,
                  "publisher": {"@id": ORIGIN + "/#organization"}}]
        head = ('<meta property="og:site_name" content="Old Template Studio">' +
                ''.join('<script type="application/ld+json">'+json.dumps(node)+'</script>' for node in nodes))
        markup = (f'<html lang="{lang}"><head><title>Section {n} | {name}</title>{head}</head>'
                  '<body><main><h1>Care information</h1><p>Independent clinic services and appointments for local patients.</p>'
                  '<a href="/care">Care</a><a href="/about">About</a></main></body></html>')
        routes[path] = httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, text=markup)
    return audited(routes, start=ORIGIN+"/", sitemap=tuple(routes), max_pages=3)


def test_multiple_independent_identity_channels_outweigh_one_stale_og_name():
    outcome = identity_site()
    found = brand.resolve(outcome.result)
    assert found["name"] == "Coastline Health"
    assert found["source"] == "site" and found["confirmed"] is False
    assert found["pages"] == 3


def test_owner_identity_still_overrides_disagreeing_metadata():
    outcome = identity_site()
    found = brand.resolve(outcome.result, "Owner Confirmed Practice")
    assert found["name"] == "Owner Confirmed Practice" and found["source"] == "typed" and found["confirmed"]


def test_declared_same_entity_alias_is_not_an_identity_contradiction():
    outcome = identity_site(alternate=True)
    findings = outcome.by_id["STR-5"].findings
    assert not any("brand @id(s) carry a different name" in f.title for f in findings)


def test_localized_same_entity_names_preserve_context_without_claiming_a_contradiction():
    outcome = identity_site(localized=True)
    check = outcome.by_id["STR-5"]
    assert not any("brand @id(s) carry a different name" in f.title for f in check.findings)
    assert not any("brand is named" in f.title for f in check.findings)
    assert check.evidence.get("localized_name_observations")


def test_unexplained_same_language_same_entity_conflict_remains_detectable():
    outcome = identity_site(conflicting=True)
    assert any("brand @id(s) carry a different name" in f.title for f in outcome.by_id["STR-5"].findings)


@pytest.mark.parametrize("a,b", [("Northern Light", "NORTHERNLIGHT"), ("Güneş Fırın", "GUNES FIRIN"),
                                  ("صحة الساحل", "صحةالساحل"), ("健康医院", "健康医院")])
def test_full_identity_normalization_preserves_non_latin_names(a, b):
    assert brand.compact(a) and brand.same_name(a, b)


def high_finding(*, confidence=Confidence.ESTIMATED, url=ORIGIN+"/", severity=Severity.S2, rationale=Rationale.MEASURED.value):
    return Finding("RND-1", "Rendering evidence", severity, confidence, rationale, [], scope_for([url]),
                   {"pages": [{"url": url, "raw_words": 0, "rendered_words": 200}]},
                   "Substantive content available", "Inspect the captured rendering difference.")


def test_estimated_high_is_capped_by_the_shared_policy():
    # A standard shared entry point, not a special renderer-only severity change.
    from maya_audit.severity import apply
    f = high_finding()
    apply([CheckResult("RND-1", "Rendering", "findings", "", [f])],
          NS(pages=[], config={}, origin=ORIGIN, start_url=ORIGIN+"/"))
    assert f.severity in (Severity.S3, Severity.S4)
    assert f.evidence["severity_assessment"]["source_severity"] == "S2"


def test_verified_critical_homepage_retrieval_is_not_universally_downgraded():
    from maya_audit.severity import apply
    f = high_finding(confidence=Confidence.VERIFIED, severity=Severity.S1)
    f.check_id = "IDX-3"
    apply([CheckResult("IDX-3", "Redirects", "findings", "", [f])],
          NS(pages=[], config={}, origin=ORIGIN, start_url=ORIGIN+"/"))
    assert f.severity == Severity.S1
    assert f.evidence["severity_assessment"]["reach"]["kind"] == "homepage_or_key_page"


def keyword_case(query="orion", *, links=None, types=None):
    from maya_audit.dataforseo import insights
    item = {"keyword_data": {"keyword": query, "keyword_info": {"search_volume": 150}},
            "ranked_serp_element": {"serp_item": {"type": "organic", "rank_group": 1,
                "url": "https://orion.example/", "links": links}},
            "serp_item_types": types or ["organic"], "last_updated_time": "2026-10-20 10:00:00 +00:00"}
    summary, data = insights._ranked({"tasks": [{"result": [{"total_count": 400, "items": [item]}]}]})
    section = {"checks": [{"check_id": "DFS-4", "status": "observed", "summary": summary, "evidence": {"data": data}}]}
    insights.apply_relevance(section, brand="Orion", domain="orion.example", texts=["Garden irrigation systems"])
    return data


def test_bare_single_word_identity_needs_query_corroboration_not_rank_one_alone():
    data = keyword_case()
    assert data["keyword_assessments"][0]["category"] == "ambiguous"
    assert data["provider_table"]["rows"] == [["orion", 150, 1, "https://orion.example/"]]


def test_own_organic_sitelinks_corroborate_an_ambiguous_named_query():
    data = keyword_case(links=[{"type": "link_element", "url": "https://orion.example/contact", "title": "Contact"}])
    assessment = data["keyword_assessments"][0]
    assert assessment["category"] == "branded"
    assert any(s.get("kind") == "serp_domain_identity" for s in assessment["sources"])
    assert data["total_count"] == 400 and data["relevance"]["branded"] == 1


def test_knowledge_panel_presence_flag_does_not_identify_its_organization():
    data = keyword_case(types=["organic", "knowledge_graph"])
    assert data["keyword_assessments"][0]["category"] == "ambiguous"


def test_sitelinks_on_an_unrelated_domain_cannot_corroborate_identity():
    data = keyword_case(links=[{"type": "link_element", "url": "https://unrelated.example/contact"}])
    assert data["keyword_assessments"][0]["category"] == "ambiguous"


def test_generic_service_query_does_not_become_branded_from_sitelinks():
    data = keyword_case("garden irrigation", links=[{"type": "link_element", "url": "https://orion.example/services"}])
    assert data["keyword_assessments"][0]["category"] != "branded"


def test_shared_policy_does_not_restore_a_finding_deliberately_made_informational():
    from maya_audit.severity import apply
    f = high_finding(confidence=Confidence.VERIFIED, severity=Severity.S1)
    checks = [CheckResult('RND-1', 'Rendering', 'findings', '', [f])]
    apply(checks)
    f.severity = Severity.INFO  # e.g. reader requalification, not a different source finding
    apply(checks)
    assert f.severity == Severity.INFO
    assert f.evidence['severity_assessment']['source_severity'] == 'S1'


def test_shared_policy_is_idempotent_and_keeps_action_metadata_in_agreement():
    from maya_audit.severity import apply
    from maya_audit.models import to_jsonable
    import copy
    f = to_jsonable(high_finding())
    f['evidence']['judgment'] = {'action': {'priority': {'severity': 'S2'}}}
    checks = [{'check_id': 'RND-1', 'findings': [f]}]
    apply(checks)
    assert f['evidence']['judgment']['action']['priority']['severity'] == f['severity']
    first = copy.deepcopy(checks)
    apply(checks)
    assert checks == first


@pytest.mark.parametrize('cosmetic,expected', [(True, Severity.INFO), (False, Severity.S2)])
def test_shared_template_alone_does_not_make_a_functional_defect_cosmetic(cosmetic, expected):
    from maya_audit.severity import apply
    f = high_finding(confidence=Confidence.VERIFIED)
    f.scope['kind'] = 'template'
    if cosmetic:
        f.evidence['impact_type'] = 'cosmetic'
    apply([CheckResult('RND-1', 'Rendering', 'findings', '', [f])])
    assert f.severity == expected


def retrieval_dependency_fixture(*, link_status=503, source='crawl'):
    from copy import deepcopy
    page = ORIGIN + '/appointments'
    f = to_jsonable(high_finding(confidence=Confidence.VERIFIED, severity=Severity.S1, url=page))
    f.update(id='IDX-1-failure', check_id='IDX-1', title='1 URL(s) return a server error (5xx) on every attempt')
    f['evidence'] = {'pages': [{'url': page, 'status': 503, 'attempts': [{'status': 503}, {'status': 503}]}]}
    link = deepcopy(f)
    link.update(id='ACC-8-link', check_id='ACC-8', title='1 of 1 link(s) in llms.txt lead to pages that do not work (server error)', severity='S4')
    link['scope'] = {'kind': 'page', 'count': 1, 'urls': [ORIGIN+'/llms.txt']}
    link['evidence'] = {'file': ORIGIN+'/llms.txt', 'links': {'checked': 1, 'not_working': 1, 'not_working_urls': [page]},
                        'not_working': [{'url': page, 'source': source, 'status': link_status, 'kind': 'server_error', 'works': False}]}
    return [{'check_id': 'IDX-1', 'status': 'findings', 'findings': [f]},
            {'check_id': 'ACC-8', 'status': 'findings', 'findings': [link]}]


def test_same_captured_server_failure_in_llms_is_one_repair_with_preserved_membership():
    from maya_audit.related_evidence import reconcile
    before = retrieval_dependency_fixture()
    after = reconcile(before, {})
    assert len(after[0]['findings']) == 1 and not after[1]['findings']
    assert before[1]['findings']  # caller's source evidence is immutable
    records = after[1]['evidence']['dependent_retrieval_observations']
    assert records[0]['finding']['id'] == 'ACC-8-link'
    refs = after[0]['findings'][0]['evidence']['dependent_observations']
    assert refs[0]['finding_id'] == 'ACC-8-link' and refs[0]['urls'] == [ORIGIN+'/appointments']
    assert reconcile(after, {}) == after


@pytest.mark.parametrize('status,source', [(404,'crawl'), (503,'light request'), (200,'crawl')])
def test_different_failure_or_client_context_is_not_suppressed(status, source):
    from maya_audit.related_evidence import reconcile
    after = reconcile(retrieval_dependency_fixture(link_status=status, source=source), {})
    assert after[1]['findings']


def test_declared_departments_do_not_become_conflicting_parent_brand_names():
    from maya_audit.checks.structure import str5_entity
    from maya_audit.config import CrawlConfig
    from maya_audit.structure_data import StructureData
    outcome = identity_site()
    for page in outcome.result.pages:
        if page.analysis:
            for item in page.analysis.get('_structured_items', []):
                node = item['data']
                if node.get('@type') == 'Organization':
                    node['department'] = [{'@type': 'Organization', '@id': ORIGIN+'/#dept'+str(n),
                                           'name': name} for n, name in enumerate(('Surgery', 'Paediatrics', 'Physiotherapy'))]
    check = str5_entity(outcome.result, CrawlConfig(), [p for p in outcome.result.pages if p.analysis], set(), outcome.result.structure)
    assert not any('brand is named' in f.title for f in check.findings)
    assert check.evidence.get('department_names_not_counted')


def test_own_declared_alias_has_page_provenance_not_owner_confirmation():
    from maya_audit.dataforseo import insights
    outcome = identity_site(alternate=True)
    data = {'total_count': 12, 'table': {'columns': ['Keyword','Searches','Position','Page'],
            'rows': [['Coastline Medical', 40, 2, ORIGIN+'/care']]}}
    section = {'checks': [{'check_id': 'DFS-4', 'status': 'observed', 'summary': '', 'evidence': {'data': data}}]}
    insights.apply_relevance(section, brand='Coastline Health', domain='fieldwork.example', texts=[], pages=outcome.result.pages)
    a = data['keyword_assessments'][0]
    assert a['category'] == 'branded'
    assert any(r.get('kind') == 'declared_identity_alias' and r.get('url') for r in a['sources'])
    assert not any(r.get('source') == 'owner profile' for r in a['sources'])


def test_other_organization_and_product_names_are_not_automatic_brand_aliases():
    from maya_audit.brand import declared_aliases
    outcome = identity_site()
    record = next(p for p in outcome.result.pages if p.analysis)
    record.analysis['_structured_items'].append({'data': {'@type': 'Organization', 'url': 'https://other.example',
         'name': 'Coastline Health', 'alternateName': 'Unrelated Enterprise'}})
    record.analysis['_structured_items'].append({'data': {'@type': 'Product', 'name': 'Resold Widget'}})
    values = declared_aliases(outcome.result.pages, 'Coastline Health', 'fieldwork.example')
    assert not any(r['name'] in ('Unrelated Enterprise', 'Resold Widget') for r in values)


def test_new_audit_and_explicit_reassessment_share_severity_and_action_decisions():
    from maya_audit.report import build_report
    from maya_audit.judgments import qualify_report
    from maya_audit.reanalysis import markdown
    import copy
    outcome = identity_site()
    # This is an ordinary mocked audit through the real orchestration entry point.
    report = build_report(outcome.result, outcome.gates, outcome.checks)
    original = copy.deepcopy(report)
    revised = qualify_report(report)
    assert report == original
    assert revised['brand'] == report['brand']
    assert next(c for c in report['checks'] if c['check_id']=='STR-5')['evidence']['identity_inputs']['complete']
    assert revised['problem_summary']['problems'] == report['problem_summary']['problems']
    for check in revised['checks']:
        for f in check['findings']:
            assessment = f['evidence']['severity_assessment']
            assert assessment['severity'] == f['severity']
            action = (f['evidence'].get('judgment') or {}).get('action') or {}
            if action:
                assert action['priority']['severity'] == f['severity']
            if f['confidence'] == 'estimated':
                assert f['severity'] not in ('S1', 'S2')
    text = markdown(revised)
    assert 'Confidence:' in text and 'Severity:' in text


@pytest.mark.parametrize('retained_locale_evidence', [True, False])
def test_saved_identity_count_uses_same_locale_qualification_without_guessing_missing_context(retained_locale_evidence):
    import copy
    from maya_audit.report import build_report
    from maya_audit.judgments import qualify_report
    outcome = identity_site(localized=True)
    report = build_report(outcome.result, outcome.gates, outcome.checks)
    check = next(c for c in report['checks'] if c['check_id'] == 'STR-5')
    legacy = to_jsonable(high_finding(confidence=Confidence.ESTIMATED, severity=Severity.S4))
    legacy.update(id='STR-5-old-name-count', check_id='STR-5', title='The brand is named 3 different ways')
    legacy['evidence'] = {'variants': [{'normalized': name.lower(), 'name': name} for name in
                         ('Coastline Health', 'Kiyi Saglik', 'Old Template Studio')]}
    check['findings'].append(legacy)
    if not retained_locale_evidence:
        check['evidence'].pop('localized_name_observations', None)
    original = copy.deepcopy(report)
    revised = qualify_report(report)
    assert report == original
    checked = next(c for c in revised['checks'] if c['check_id'] == 'STR-5')
    retained = any(f['id'] == legacy['id'] for f in checked['findings'])
    assert retained is not retained_locale_evidence
    if retained_locale_evidence:
        assert checked['evidence']['localized_count_reassessment'][0]['finding']['id'] == legacy['id']
        assert checked['status'] != 'pass'
