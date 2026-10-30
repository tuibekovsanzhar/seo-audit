"""Evidence-led lexical relevance; observations are traceable, never semantic proof or affiliation inference."""
from urllib.parse import urlsplit, unquote


def assess(keyword, ranking_url, *, names, vocabulary, common, first, whole, glued,
           pages, domain, aliases=(), organizations=(), corpus=(), brand=None, content_context=None, serp_evidence=(), site_aliases=()):
    from . import insights as i
    from ..brand import compact
    raw = i._tokens(keyword)
    def token(word):
        # Conservative Turkish plural/possessive forms; identity matching stays exact below.
        for ending in ('lerimiz', 'larimiz', 'leriniz', 'lariniz', 'lerinin', 'larinin', 'leri', 'lari', 'ler', 'lar', 'si'):
            if len(word) >= len(ending) + 4 and word.endswith(ending):
                word = word[:-len(ending)]
                break
        if len(word) >= 7 and word.endswith('gi'):
            word = word[:-2] + 'k'  # geleneği / gelenek; do not truncate short names
        return i._stem(word)
    def vocab(texts):
        import re
        cleaned=[]
        for text in texts:
            normalized=' '.join(i._tokens(text))
            if partial_identity:
                pattern=r'(?<!\w)'+r'\s+'.join(map(re.escape,i._tokens(brand)))+r'(?!\w)'
                normalized=re.sub(pattern,'',normalized)
            cleaned.extend(i._tokens(normalized))
        return {token(w)for w in cleaned if w not in i._STOP and len(w)>=2}
    definition = 'nedir' in raw or ('ne' in raw and 'demek' in raw) or ('what' in raw and 'is' in raw)
    words = {token(w) for w in raw if w not in i._STOP and not (definition and w == 'demek')}
    partial_identity = bool(brand and len(i._tokens(brand)) > 1 and len(raw) == 1 and raw[0] in i._tokens(brand))
    vocabulary = {token(w) for w in vocabulary}
    if partial_identity:
        # A repeated brand word in global titles is not independent service evidence.
        vocabulary -= {token(w) for w in i._tokens(brand)}
    matched_page = False
    sources = []
    dimensions = {key: 'unknown' for key in ('brand_identity', 'related_organization', 'service_relevance',
                                           'local_relevance', 'editorial_relevance', 'unrelated_intent')}

    def result(category, reason, refs):
        dimensions['brand_identity'] = 'supported' if category == i.BRANDED else 'not_established'
        dimensions['related_organization'] = 'supported' if category == 'related_organization' else 'not_established'
        dimensions['unrelated_intent'] = 'supported' if category == i.UNRELATED else 'not_established'
        return category, {'reason': reason, 'sources': refs, 'dimensions': dimensions,
                          'uncertain': category == i.AMBIGUOUS or (category == i.RELEVANT and not matched_page),
                          'ranking_page_status': 'saved_readable_evidence' if matched_page else 'not_fetched_or_unavailable',
                          'evidence_gaps': [] if matched_page else [{'url': ranking_url, 'reason': 'Ranking page readable content was not assessed; URL/context estimates are provisional.'}],
                          'query_intent': 'explanatory' if definition else 'not_established',
                          'limitation': 'Lexical context is not semantic proof or evidence of organizational ownership.'}


    def named(values, confirmed=False):
        for value in values:
            key = compact(' '.join(i._tokens(value)))
            for start in range(len(raw)):
                for end in range(start + 1, len(raw) + 1):
                    if compact(' '.join(raw[start:end])) == key:
                        # A common-word alias alone is not enough to settle intent.
                        if not confirmed and i.common_word_brand(value) and len(raw) == 1:
                            continue
                        return value
        return None

    alias = named(aliases, confirmed=True)
    organization = named(organizations)
    if alias or organization:
        category = i.BRANDED if alias else 'related_organization'
        return result(category, 'owner-confirmed name', [{'source': 'owner profile',
                                'kind': 'brand_alias' if alias else 'related_organization', 'name': alias or organization}])
    # A named query still needs query-level corroboration when a bare word can
    # name a subject as well as an organization. Rank one alone is not ownership.
    own_host = (domain or '').lower().removeprefix('www.')
    def owned(url):
        part = urlsplit(str(url or ''))
        host = (part.hostname or '').lower().removeprefix('www.')
        return bool(own_host and part.scheme in ('https', 'http') and (host == own_host or host.endswith('.' + own_host)))
    identity_refs = []
    for record in serp_evidence:
        if record.get('result_type') != 'organic' or not owned(record.get('ranking_url')):
            continue
        links = [link for link in record.get('sitelinks') or [] if link.get('type') == 'link_element' and owned(link.get('url'))]
        if links:
            identity_refs.append({'kind': 'serp_domain_identity', 'source': record.get('source'),
                                  'url': record.get('ranking_url'), 'observed_at': record.get('observed_at'),
                                  'sitelinks': links, 'limitation': 'Corroborates a named query only; generic service rankings do not establish branded intent.'})
    full_identity = named([brand], confirmed=True) if brand else None
    bare_single = bool(brand and len(i._tokens(brand)) == 1 and raw == i._tokens(brand))
    acronym = bool(brand and brand.isupper() and 2 <= len(brand) <= 5)
    if full_identity and identity_refs:
        return result(i.BRANDED, 'named query corroborated by owned organic sitelinks', identity_refs)
    if bare_single and not acronym:
        return result(i.AMBIGUOUS, 'bare identity word without query-level corroboration; confirm alias or inspect retained SERP identity evidence', [])
    site_alias = named([r['name'] for r in site_aliases])
    if site_alias:
        refs = [r for r in site_aliases if r['name'] == site_alias]
        return result(i.BRANDED, 'explicit own-entity declared alias (not owner confirmation)', refs)
    lexical = i.classify_keyword(keyword, names, vocabulary, common, first=first, whole=whole, glued=glued)
    # The legacy helper accepts any two name words, including a generic service in a long name.
    # Only the full identity (or an explicitly confirmed alias above) establishes a multiword brand here.
    full_name = named([brand]) if brand else None
    if lexical == i.BRANDED and full_name:
        return result(lexical, 'brand-name match', [{'source': 'audit brand', 'name': brand}])
    if lexical == i.BRANDED:
        own = i._tokens(brand)
        if len(raw) >= 2 and len(raw) < len(own) and raw == own[:len(raw)]:
            return result(i.AMBIGUOUS, 'plausible shortened brand name; confirm alias or establish declared identity before using it',
                          [{'source': 'audit brand prefix (candidate, not confirmed)', 'name': brand, 'candidate': keyword}])
        lexical = i.AMBIGUOUS

    parts = urlsplit(str(ranking_url or ''))
    own = (domain or '').lower().removeprefix('www.')
    host = (parts.hostname or '').lower().removeprefix('www.')
    same_site = bool(own and (host == own or host.endswith('.' + own)))
    matched_page = False
    context_words = set()
    editorial = False
    explanatory_content = False
    local_words = set()
    if same_site and parts.scheme in ('http', 'https'):
        path = unquote(parts.path)
        path_words = i.site_vocabulary([path], names)
        context_words |= {token(w) for w in path_words}
        if path_words:
            sources.append({'source': 'ranking URL path', 'url': ranking_url, 'text': path})
        for page in pages:
            if getattr(page, 'url', '').rstrip('/') != str(ranking_url).rstrip('/'):
                continue
            if hasattr(page, 'readable_document') and not page.readable_document():
                continue
            matched_page = True
            texts = i.page_texts([page])
            for text in texts:
                terms = i._tokens(text)
                explanatory_content |= 'nedir' in terms or ('ne' in terms and 'demek' in terms)
            analysis = getattr(page, 'analysis', None) or {}
            # Actual readable blocks, with shared navigation removed by main_content. No text_sketch hashes.
            blocks = (content_context or {}).get(page.url) or []
            body = analysis.get('main_text')
            if isinstance(body, str) and body.strip():
                blocks = [*blocks, body[:12000]]
            if blocks:
                context_words |= vocab(blocks)
                snippets = [b[:1200] for b in blocks if words & vocab([b])][:3]
                if snippets:
                    sources.append({'source': 'saved readable content blocks (shared furniture excluded)',
                                    'url': page.url, 'requested_at': getattr(page, 'requested_at', None),
                                    'view': getattr(page, 'view', 'unknown'), 'texts': snippets,
                                    'provenance': getattr(page, 'classification_evidence', [])})
            import json
            def nodes(value):
                if isinstance(value, dict):
                    yield value
                    for v in value.values():
                        yield from nodes(v)
                elif isinstance(value, list):
                    for v in value:
                        yield from nodes(v)
            structured = [item.get('data') for item in analysis.get('_structured_items') or [] if isinstance(item, dict)]
            editorial |= bool(set((analysis.get('structured_data') or {}).get('types') or []) & {'Article', 'BlogPosting', 'NewsArticle'})
            for block in analysis.get('json_ld_blocks') or []:
                try:
                    structured.append(json.loads(block) if isinstance(block, str) else block)
                except (ValueError, TypeError):
                    pass
            for node in nodes(structured):
                types = node.get('@type') or []
                types = [types] if isinstance(types, str) else types
                editorial |= any(t in ('Article', 'BlogPosting', 'NewsArticle') for t in types)
                if isinstance(node.get('addressLocality'), str):
                    local_words |= i.site_vocabulary([node['addressLocality']], set())
                    sources.append({'source': 'saved structured addressLocality', 'url': page.url,
                                    'requested_at': getattr(page, 'requested_at', None), 'text': node['addressLocality']})

            # Generic CMS Article markup is not sufficient on a branch/business page.
            types = set((analysis.get('structured_data') or {}).get('types') or [])
            if types & {'Restaurant', 'LocalBusiness', 'Store', 'BankOrCreditUnion', 'ContactPage'}:
                editorial = False
            if 'og' in analysis and 'structured_data' in analysis:
                from ..checks.structure import page_kind
                kind, basis = page_kind(page, parts.scheme + '://' + parts.netloc + '/')
                editorial = kind == 'article' and bool(basis and basis.startswith('path '))
            if texts:
                matched_page = True
                context_words |= vocab(texts)
                sources.append({'source': 'saved page title/headings/description', 'url': page.url,
                                'requested_at': getattr(page, 'requested_at', None),
                                'view': getattr(page, 'view', 'unknown'), 'texts': texts,
                                'provenance': getattr(page, 'classification_evidence', [])})
    hits = words & context_words
    # A supported short topic token can identify a service; matching the host alone never does.
    # Function/intent words do not name another organization. Unknown content words must not be
    # swallowed by a majority match (e.g. another restaurant plus the same generic service).
    intent = set(i._tokens('en yakin near nearest nedir what is nasil how siparis order online'))
    unmatched = words - context_words - intent
    supported = bool(words and hits and not unmatched)
    if supported:
        dimensions['editorial_relevance' if editorial or (definition and explanatory_content) else 'service_relevance'] = 'supported' if matched_page else 'provisional'
        if words & {token(w) for w in local_words}:
            dimensions['local_relevance'] = 'supported'
        elif any(w in i._tokens(keyword) for w in ('yakin', 'nearest', 'nearby')):
            dimensions['local_relevance'] = 'intent_only'
        elif matched_page and not editorial and any(segment in ('sube', 'subeler', 'branches', 'locations') for segment in parts.path.split('/')) and bool(words & vocab([unquote(parts.path.rstrip('/').rsplit('/', 1)[-1])])):
            dimensions['local_relevance'] = 'supported'

        return result(i.RELEVANT, 'ranking-page topic match (lexical, review intent)', sources)

    global_hits = words & vocabulary
    if words and global_hits and not (words - vocabulary - intent):
        dimensions['editorial_relevance' if editorial or (definition and explanatory_content) else 'service_relevance'] = 'supported' if matched_page else 'provisional'
        return result(i.RELEVANT, 'site vocabulary match (lexical, review intent)', [{'source': 'supplied site titles/headings/descriptions or owner industry',
            'matched': sorted(global_hits), 'texts': [text for text in corpus if words & i.site_vocabulary([text], names)]}])

    # Ordinary-name searches with a different subject keep their existing explicit unrelated classification.
    conflicting_common = common and any(w in names for w in raw) and not global_hits and len(words - names) >= 2
    if hits or global_hits or (same_site and not matched_page and not conflicting_common) or len(words) <= 1:
        return result(i.AMBIGUOUS, 'insufficient or mixed contextual evidence', sources)
    return result(i.UNRELATED if conflicting_common else i.AMBIGUOUS, 'conflicting ordinary-word intent' if conflicting_common else 'no supported topic match; missing context is not unrelated intent', sources)
