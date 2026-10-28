"""The on-demand benchmark's accounting is tested with synthetic data, never real sites."""
from copy import deepcopy
import json

import httpx
import pytest

from scripts import real_sites_benchmark as b


URL = "https://synthetic.test/services"


def fixture():
    label = {"id": "missing-heading", "check_id": "STR-2", "reason": "No meaningful H1 in independently reviewed source",
             "status": "verified", "urls": [URL], "verification": {"collection_digest": "frozen-a"}}
    report = {"benchmark": {"collection_digest": "frozen-a"}, "checks": [
        {"check_id": "STR-2", "status": "pass", "coverage": {"not_assessed": []}, "findings": []}],
        "crawl": {"pages": [{"url": URL, "body_bytes": 500, "content_checks_eligible": True,
                             "analysis": {"title": "Independent example"}}]}}
    finding = {"id": "STR-2-example", "check_id": "STR-2", "severity": "S3", "title": "No meaningful H1",
               "scope": {"urls": [URL], "count": 1}}
    return label, report, finding


def labels(label, positive=True):
    return {"must_find": [label] if positive else [], "must_not_find": [] if positive else [label]}


def test_hit_and_real_miss_are_not_false_alarm_counts():
    label, report, finding = fixture()
    assert b.score(report, labels(label))["counts"] == {"miss": 1}
    report["checks"][0]["findings"].append(finding)
    assert b.score(report, labels(label))["counts"] == {"hit": 1}


def test_false_alarm_and_supported_negative():
    label, report, finding = fixture()
    assert b.score(report, labels(label, False))["counts"] == {"correct_negative": 1}
    report["checks"][0]["findings"].append(finding)
    assert b.score(report, labels(label, False))["counts"] == {"false_alarm": 1}


@pytest.mark.parametrize("status", ["not_assessed", "not_applicable", "partial"])
def test_unassessed_never_becomes_correct_negative_or_miss(status):
    label, report, _ = fixture()
    report["checks"][0]["status"] = status
    for positive in (False, True):
        assert b.score(report, labels(label, positive))["counts"] == {"unassessed": 1}


def test_unread_page_does_not_prove_negative():
    label, report, _ = fixture()
    report["crawl"]["pages"][0]["body_bytes"] = 0
    assert b.score(report, labels(label, False))["counts"] == {"unassessed": 1}


def test_unread_rest_of_site_does_not_invalidate_an_assessed_page_negative():
    label, report, _ = fixture()
    check = report["checks"][0]
    check.update(status="partial", coverage={"not_assessed": [{"part": "pages found but not read", "count": 400}]})
    assert b.score(report, labels(label, False))["counts"] == {"correct_negative": 1}
    report["crawl"]["pages"] = []
    assert b.score(report, labels(label, False))["counts"] == {"unassessed": 1}


def test_language_gap_is_scoped_only_when_its_membership_is_complete():
    label, report, _ = fixture()
    label["check_id"] = "STR-12"
    check = report["checks"][0]
    check.update(check_id="STR-12", status="partial", coverage={"not_assessed": [{"part": "content language of pages"}]},
                 evidence={"language_not_assessed": [{"url": URL + "/short"}], "language_not_assessed_count": 1})
    assert b.score(report, labels(label, False))["counts"] == {"correct_negative": 1}
    check["evidence"]["language_not_assessed_count"] = 2
    assert b.score(report, labels(label, False))["counts"] == {"unassessed": 1}
    check["evidence"] = {"language_not_assessed": [{"url": URL}], "language_not_assessed_count": 1}
    assert b.score(report, labels(label, False))["counts"] == {"unassessed": 1}


def test_provisional_historical_claims_are_not_golden_facts():
    label, report, finding = fixture()
    label["status"] = "provisional"
    report["checks"][0]["findings"] = [finding]
    assert b.score(report, labels(label))["counts"] == {"provisional": 1}


def test_golden_label_is_bound_to_the_reviewed_collection():
    label, report, _ = fixture()
    report["benchmark"]["collection_digest"] = "different-response-bytes"
    assert b.score(report, labels(label, False))["counts"] == {"unassessed": 1}


def test_unlabelled_finding_is_not_automatically_a_false_alarm():
    label, report, finding = fixture()
    finding["check_id"] = "IDX-1"
    report["checks"][0]["findings"] = [finding]
    result = b.score(report, labels(label))
    assert result["unlabelled_findings"] == 1
    assert "false_alarm" not in result["counts"]


def test_blocked_collection_keeps_verified_assertions_unassessed(tmp_path, capsys):
    label, _, _ = fixture()
    site = {"id": "example", "expectations": labels(label)}
    (tmp_path / "example").mkdir()
    b.write(tmp_path / "example/result.json", {"status": "blocked", "error_type": "TimeoutError", "seconds": 12})
    result = b.score_run(tmp_path, [site])[0]
    assert result["status"] == "blocked" and result["error_type"] == "TimeoutError"
    assert result["counts"] == {"unassessed": 1}
    assert "blocked" in capsys.readouterr().out


def test_scope_and_severity_select_the_actual_disputed_conclusion():
    label, report, finding = fixture()
    label["severity"] = "S1"
    assert not b.matches(finding, label, report)
    label["severity"] = "S3"
    assert b.matches(finding, label, report)
    finding["scope"]["urls"] = ["https://synthetic.test/another"]
    assert not b.matches(finding, label, report)


def test_comparison_rejects_changed_truth_labels_and_changed_observations():
    row = {"site": "example", "collection_digest": "same-responses", "labels_digest": "same-labels",
           "assertions": [{"id": "a", "result": "hit"}]}
    before = {"sites": [row]}
    after = deepcopy(before)
    assert b.compare(before, after) == [{"site": "example", "regressions": []}]
    after["sites"][0]["assertions"][0]["result"] = "unassessed"
    assert b.compare(before, after)[0]["regressions"] == ["a"]
    for key in ("collection_digest", "labels_digest"):
        changed = deepcopy(before)
        changed["sites"][0][key] = "different"
        with pytest.raises(ValueError, match="changed evidence or labels"):
            b.compare(before, changed)


def test_provisional_only_scorecard_cannot_claim_non_regression():
    card = {"sites": [{"site": "example", "collection_digest": "a", "labels_digest": "b",
                        "assertions": [{"id": "not-golden", "result": "provisional"}]}]}
    with pytest.raises(ValueError, match="No independently verified"):
        b.compare(card, deepcopy(card))


def test_variant_observation_is_distinct_from_actionable_duplicate_label():
    label, report, finding = fixture()
    label["severities"] = ["S1", "S2", "S3", "S4"]
    assert b.matches(finding, label, report)
    finding["severity"] = "Info"
    assert not b.matches(finding, label, report)


def test_live_collection_requires_explicit_opt_in():
    with pytest.raises(SystemExit) as error:
        b.main(["collect"])
    assert error.value.code == 2


def test_child_environment_drops_all_provider_credentials(monkeypatch, tmp_path):
    monkeypatch.setenv("UNKNOWN_PROVIDER_SECRET", "synthetic-do-not-inherit")
    monkeypatch.setenv("MAYA_AUDIT_FIRECRAWL_API_KEY", "synthetic-not-a-real-key")
    env = b.child_environment(tmp_path)
    assert "UNKNOWN_PROVIDER_SECRET" not in env and "MAYA_AUDIT_FIRECRAWL_API_KEY" not in env
    assert not __import__("pathlib").Path(env["MAYA_AUDIT_ENV_FILE"]).exists()
    assert env["MAYA_AUDIT_FIRECRAWL"] == "off"


def test_frozen_missing_request_fails_closed_and_preserves_method(tmp_path):
    gaps = []
    with httpx.Client(transport=b.frozen_transport(tmp_path, [], gaps)) as client:
        with pytest.raises(httpx.ConnectError, match="absent from frozen evidence"):
            client.head(URL)
    assert gaps == [{"url": URL, "method": "HEAD", "reason": "no frozen request evidence"}]


def test_offline_replay_blocks_dns_even_outside_the_injected_transport():
    import socket
    original = socket.getaddrinfo
    with b.offline_network():
        with pytest.raises(RuntimeError, match="prohibits network/DNS"):
            socket.getaddrinfo("unrelated-synthetic.invalid", 443)
        with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, text="Frozen"))) as client:
            assert client.get(URL).text == "Frozen"
    assert socket.getaddrinfo is original


def test_frozen_response_integrity_and_no_reuse_of_attempts(tmp_path):
    body = b"<h1>Synthetic clinic</h1>"
    (tmp_path / "000000.body").write_bytes(body)
    request = httpx.Request("GET", URL)
    records = [{"id": "000000", "request_key": b.request_key(request), "url": URL,
                "method": "GET", "status": 200, "headers": {"content-type": "text/html"},
                "stream_complete": True, "body_sha256": b.hashlib.sha256(body).hexdigest()}]
    transport = b.frozen_transport(tmp_path, records, [])
    response = transport.handle_request(request)
    assert response.read() == body
    with pytest.raises(httpx.ConnectError, match="absent from frozen evidence"):
        transport.handle_request(request)
    (tmp_path / "000000.body").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="Frozen response changed"):
        b.frozen_transport(tmp_path, records, []).handle_request(request)


def test_site_manifest_has_ten_distinct_sector_examples_and_pending_labels():
    sites = b.load_sites()
    assert len(sites) == 10 and len({s["id"] for s in sites}) == 10
    assert sum(s["language"] == "en" for s in sites) == 2
    assert len({s["sector"] for s in sites}) >= 7
    # Allegations without independently reviewed saved bytes must stay provisional.
    assert all(label["status"] in ("provisional", "verified") for site in sites
               for group in ("must_find", "must_not_find") for label in site["expectations"][group])


def test_extracted_checkpoint_uses_manifest_reference_without_a_git_directory(monkeypatch, tmp_path):
    (tmp_path/'maya_audit').mkdir()
    (tmp_path/'maya_audit'/'__init__.py').write_text('# synthetic engine\n')
    (tmp_path/'scripts').mkdir()
    (tmp_path/'scripts'/'real_sites_benchmark.py').write_text('# synthetic runner\n')
    (tmp_path/'RELEASE-SNAPSHOT.json').write_text('{"base_commit": "synthetic-base-reference"}')
    monkeypatch.setattr(b, 'ROOT', tmp_path)
    state = b.source_state()
    assert state['base_commit'] == 'synthetic-base-reference'
    assert state['files']['maya_audit/__init__.py']
    assert 'Reference identity only' in state['base_commit_note']
