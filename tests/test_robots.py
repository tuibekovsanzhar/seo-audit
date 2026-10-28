from maya_audit.robots import crawl_delay, decide, parse_robots, policy_from_response

URL = "https://example.com"


def check(text, path, token="Maya-Audit"):
    return decide(parse_robots(text), token, URL + path)


def test_longest_match_wins():
    text = "User-agent: *\nDisallow: /shop/\nAllow: /shop/public/\n"
    assert not check(text, "/shop/cart").allowed
    decision = check(text, "/shop/public/item")
    assert decision.allowed
    assert decision.rule.line == 3


def test_allow_wins_a_tie():
    text = "User-agent: *\nDisallow: /page\nAllow: /page\n"
    assert check(text, "/page").allowed


def test_wildcard_and_end_anchor():
    text = "User-agent: *\nDisallow: /*.pdf$\nDisallow: /search*q=\n"
    assert not check(text, "/files/report.pdf").allowed
    assert check(text, "/files/report.pdf?download=1").allowed
    assert not check(text, "/search?page=2&q=shoes").allowed


def test_specific_group_replaces_star_group():
    text = "User-agent: *\nDisallow: /\n\nUser-agent: Maya-Audit\nDisallow: /private/\n"
    decision = check(text, "/public")
    assert decision.allowed
    assert decision.group_kind == "specific"
    assert decision.group_lines == (4,)
    assert not check(text, "/private/x").allowed
    assert not check(text, "/public", token="OtherBot").allowed


def test_user_agent_match_is_case_insensitive_and_ignores_version():
    text = "User-agent: maya-audit/2.0\nDisallow: /x\n"
    assert not check(text, "/x").allowed


def test_consecutive_user_agents_share_a_group():
    text = "User-agent: GPTBot\nUser-agent: Maya-Audit\nDisallow: /both\n"
    assert not check(text, "/both").allowed
    assert not check(text, "/both", token="GPTBot").allowed


def test_empty_disallow_allows_everything_and_comments_are_ignored():
    text = "# comment\nUser-agent: * # inline\nDisallow:\n"
    decision = check(text, "/anything")
    assert decision.allowed and decision.rule is None


def test_no_matching_group_allows():
    assert check("User-agent: GPTBot\nDisallow: /\n", "/").group_kind == "none"


def test_robots_txt_itself_is_always_allowed():
    assert check("User-agent: *\nDisallow: /\n", "/robots.txt").allowed


def test_percent_encoding_is_normalized():
    text = "User-agent: *\nDisallow: /caf%C3%A9\n"
    assert not check(text, "/café").allowed
    assert not check(text, "/caf%c3%a9").allowed


def test_crawl_delay_and_sitemaps_are_recorded():
    robots = parse_robots("User-agent: Maya-Audit\nCrawl-delay: 2.5\n\nSitemap: https://example.com/s.xml\n")
    assert crawl_delay(robots, "Maya-Audit") == (2.5, 2)
    assert robots.sitemaps == [("https://example.com/s.xml", 4)]


def test_fetch_status_mapping_per_rfc_9309():
    ok = policy_from_response(URL + "/robots.txt", 200, None, b"User-agent: *\nDisallow: /a\n", 500, [])
    assert ok.mode == "parsed"
    assert policy_from_response(URL, 404, None, b"", 500, []).mode == "allow_all"
    assert policy_from_response(URL, 403, None, b"", 500, []).mode == "allow_all"
    assert policy_from_response(URL, 503, None, b"", 500, []).mode == "disallow_all"
    assert policy_from_response(URL, 429, None, b"", 500, []).mode == "disallow_all"
    # No answer is not an answer: nothing is assumed about the site, and Maya's own crawler still requests nothing.
    silent = policy_from_response(URL, None, "timeout (ReadTimeout)", b"", 500, [])
    assert silent.mode == "not_checked" and silent.cause == "no_answer" and silent.stops_requests and "RFC 9309" not in silent.reason
    assert not silent.decide("Maya-Audit", URL + "/").allowed
    blocked = policy_from_response(URL, 503, None, b"", 500, [])
    assert not blocked.decide("Maya-Audit", URL + "/").allowed
    assert blocked.decide("Maya-Audit", URL + "/robots.txt").allowed


def test_429_is_a_temporary_rate_limit_not_an_rfc_disallow():
    policy = policy_from_response(URL, 429, None, b"", 500, [])
    assert not policy.decide("Maya-Audit", URL + "/page").allowed
    assert "back off and retry later" in policy.reason
    assert "RFC" not in policy.reason


def test_challenge_body_does_not_override_4xx_status():
    for status in (400, 401, 403, 404, 410, 451, 499):
        policy = policy_from_response(URL, status, None, b"<html>Challenge</html>\nDisallow: /", 500, [])
        assert policy.mode == "allow_all" and policy.robots is None
        assert policy.decide("Maya-Audit", URL + "/page").allowed
