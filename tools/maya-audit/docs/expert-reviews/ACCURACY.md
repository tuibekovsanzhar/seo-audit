# Expert review accuracy by rule

Made by `scripts/expert_accuracy.py` from `enpara-2e5829fb.json`, `enpara-fee70191.json`, `enpara-fee70191-review3.json`, `enpara-fee70191-final.json`, `mmi-536b4b64.json`, `naturesgarden-342a0b14.json` (DECISIONS 338, 340). A card's verdict counts once for each rule on it; "wrong" is the expert's verdict, before the evidence was checked (each review file says what the evidence showed and what was fixed).

| Rule | Cards reviewed | Correct | Wrong | Wording | Incomplete | Share correct | Latest |
|---|---|---|---|---|---|---|---|
| `acc2.blocks.sample` | 1 | 0 | 1 | 0 | 0 | 0% | wrong (enpara-2e5829fb) |
| `acc3.robots_outside_head` | 1 | 0 | 0 | 0 | 1 | 0% | incomplete (mmi-536b4b64) |
| `acc8.redirecting` | 2 | 0 | 0 | 0 | 2 | 0% | incomplete (enpara-fee70191) |
| `acc9.rate_limited_429` | 1 | 0 | 1 | 0 | 0 | 0% | wrong (naturesgarden-342a0b14) |
| `idx1.4xx.referenced` | 1 | 0 | 0 | 0 | 1 | 0% | incomplete (enpara-2e5829fb) |
| `idx1.4xx.sitemap_only` | 2 | 1 | 1 | 0 | 0 | 50% | correct (enpara-fee70191-review3) |
| `idx1.error_redirect` | 1 | 0 | 0 | 0 | 1 | 0% | incomplete (enpara-fee70191-review3) |
| `idx2.temporary` | 1 | 0 | 1 | 0 | 0 | 0% | wrong (enpara-2e5829fb) |
| `idx4.different` | 1 | 0 | 1 | 0 | 0 | 0% | wrong (mmi-536b4b64) |
| `idx5.stamped` | 1 | 0 | 0 | 0 | 1 | 0% | incomplete (naturesgarden-342a0b14) |
| `idx6.alias_links` | 1 | 0 | 0 | 0 | 1 | 0% | incomplete (mmi-536b4b64) |
| `idx6.links_to_redirect` | 3 | 1 | 1 | 1 | 0 | 33% | wrong (enpara-fee70191-review3) |
| `idx8.self_canonical_copies` | 1 | 0 | 1 | 0 | 0 | 0% | wrong (enpara-fee70191-review3) |
| `judgment.generic.identity` | 1 | 0 | 0 | 0 | 1 | 0% | incomplete (mmi-536b4b64) |
| `prf1.home_ttfb` | 2 | 1 | 1 | 0 | 0 | 50% | wrong (mmi-536b4b64) |
| `prf1.slow` | 2 | 0 | 1 | 0 | 1 | 0% | wrong (mmi-536b4b64) |
| `rnd1.partial` | 2 | 0 | 0 | 0 | 2 | 0% | incomplete (naturesgarden-342a0b14) |
| `rnd3.revealed` | 1 | 0 | 0 | 0 | 1 | 0% | incomplete (mmi-536b4b64) |
| `rnd6.large` | 1 | 1 | 0 | 0 | 0 | 100% | correct (mmi-536b4b64) |
| `rnd6.late` | 1 | 1 | 0 | 0 | 0 | 100% | correct (mmi-536b4b64) |
| `shared.heading_jump_varied` | 1 | 0 | 0 | 0 | 1 | 0% | incomplete (naturesgarden-342a0b14) |
| `shared.link_no_address` | 1 | 0 | 0 | 0 | 1 | 0% | incomplete (mmi-536b4b64) |
| `str1.no_title` | 1 | 0 | 1 | 0 | 0 | 0% | wrong (mmi-536b4b64) |
| `str1.shared` | 1 | 1 | 0 | 0 | 0 | 100% | correct (mmi-536b4b64) |
| `str1.subpage_copies_parent` | 1 | 0 | 0 | 0 | 1 | 0% | incomplete (enpara-fee70191-review3) |
| `str12.headings` | 2 | 0 | 2 | 0 | 0 | 0% | wrong (naturesgarden-342a0b14) |
| `str14.no_text` | 5 | 3 | 0 | 0 | 2 | 60% | incomplete (naturesgarden-342a0b14) |
| `str15.empty_collections` | 2 | 0 | 2 | 0 | 0 | 0% | wrong (naturesgarden-342a0b14) |
| `str16.shared` | 4 | 4 | 0 | 0 | 0 | 100% | correct (mmi-536b4b64) |
| `str19.no_target` | 1 | 0 | 0 | 0 | 1 | 0% | incomplete (naturesgarden-342a0b14) |
| `str2.h1_parent_name` | 1 | 0 | 0 | 0 | 1 | 0% | incomplete (enpara-fee70191-review3) |
| `str2.hidden_h1` | 3 | 0 | 3 | 0 | 0 | 0% | wrong (naturesgarden-342a0b14) |
| `str2.home_outline` | 1 | 0 | 1 | 0 | 0 | 0% | wrong (mmi-536b4b64) |
| `str2.no_h1` | 3 | 2 | 0 | 1 | 0 | 67% | correct (enpara-fee70191-review3) |
| `str2.no_subheadings` | 1 | 0 | 1 | 0 | 0 | 0% | wrong (enpara-2e5829fb) |
| `str2.styled_subheadings` | 1 | 1 | 0 | 0 | 0 | 100% | correct (enpara-fee70191) |
| `str3.crumb_no_list` | 1 | 1 | 0 | 0 | 0 | 100% | correct (mmi-536b4b64) |
| `str3.expected_type` | 1 | 1 | 0 | 0 | 0 | 100% | correct (mmi-536b4b64) |
| `str3.product_no_identifier` | 2 | 1 | 0 | 0 | 1 | 50% | incomplete (mmi-536b4b64) |
| `str3.product_on_article` | 1 | 1 | 0 | 0 | 0 | 100% | correct (enpara-fee70191-review3) |
| `str3.qa_no_faqpage` | 1 | 0 | 1 | 0 | 0 | 0% | wrong (enpara-fee70191) |
| `str3.unparsed` | 4 | 3 | 0 | 0 | 1 | 75% | incomplete (naturesgarden-342a0b14) |
| `str5.names` | 3 | 0 | 3 | 0 | 0 | 0% | wrong (mmi-536b4b64) |
| `str7.over_100kb` | 3 | 3 | 0 | 0 | 0 | 100% | correct (mmi-536b4b64) |
| `str8.headers` | 2 | 1 | 0 | 0 | 1 | 50% | incomplete (naturesgarden-342a0b14) |
| `str9.no_return` | 2 | 2 | 0 | 0 | 0 | 100% | correct (enpara-fee70191-review3) |
| `str9.status` | 2 | 2 | 0 | 0 | 0 | 100% | correct (enpara-fee70191-review3) |
| `tseo1.head_closed_later` | 3 | 0 | 3 | 0 | 0 | 0% | wrong (enpara-fee70191-review3) |
| `tseo1.head_closed_lost` | 3 | 0 | 3 | 0 | 0 | 0% | wrong (enpara-fee70191-review3) |
| `tseo1.heading_jumps` | 1 | 1 | 0 | 0 | 0 | 100% | correct (mmi-536b4b64) |
| `tseo1.url_slug_unclear` | 1 | 0 | 0 | 0 | 1 | 0% | incomplete (mmi-536b4b64) |

Cards reviewed: 87; correct 29, wrong 27, wording 2, incomplete 29 (33% correct).
