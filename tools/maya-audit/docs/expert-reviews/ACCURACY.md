# Expert review accuracy by rule

Made by `scripts/expert_accuracy.py` from `enpara-2e5829fb.json`, `enpara-fee70191.json`, `enpara-fee70191-review3.json` (DECISIONS 338, 340). A card's verdict counts once for each rule on it; "wrong" is the expert's verdict, before the evidence was checked (each review file says what the evidence showed and what was fixed).

| Rule | Cards reviewed | Correct | Wrong | Wording | Incomplete | Share correct | Latest |
|---|---|---|---|---|---|---|---|
| `acc2.blocks.sample` | 1 | 0 | 1 | 0 | 0 | 0% | wrong (enpara-2e5829fb) |
| `acc8.redirecting` | 2 | 0 | 0 | 0 | 2 | 0% | incomplete (enpara-fee70191) |
| `idx1.4xx.referenced` | 1 | 0 | 0 | 0 | 1 | 0% | incomplete (enpara-2e5829fb) |
| `idx1.4xx.sitemap_only` | 2 | 1 | 1 | 0 | 0 | 50% | correct (enpara-fee70191-review3) |
| `idx1.error_redirect` | 1 | 0 | 0 | 0 | 1 | 0% | incomplete (enpara-fee70191-review3) |
| `idx2.temporary` | 1 | 0 | 1 | 0 | 0 | 0% | wrong (enpara-2e5829fb) |
| `idx6.links_to_redirect` | 3 | 1 | 1 | 1 | 0 | 33% | wrong (enpara-fee70191-review3) |
| `idx8.self_canonical_copies` | 1 | 0 | 1 | 0 | 0 | 0% | wrong (enpara-fee70191-review3) |
| `str1.subpage_copies_parent` | 1 | 0 | 0 | 0 | 1 | 0% | incomplete (enpara-fee70191-review3) |
| `str14.no_text` | 3 | 3 | 0 | 0 | 0 | 100% | correct (enpara-fee70191-review3) |
| `str16.shared` | 3 | 3 | 0 | 0 | 0 | 100% | correct (enpara-fee70191-review3) |
| `str2.h1_parent_name` | 1 | 0 | 0 | 0 | 1 | 0% | incomplete (enpara-fee70191-review3) |
| `str2.no_h1` | 3 | 2 | 0 | 1 | 0 | 67% | correct (enpara-fee70191-review3) |
| `str2.no_subheadings` | 1 | 0 | 1 | 0 | 0 | 0% | wrong (enpara-2e5829fb) |
| `str2.styled_subheadings` | 1 | 1 | 0 | 0 | 0 | 100% | correct (enpara-fee70191) |
| `str3.product_on_article` | 1 | 1 | 0 | 0 | 0 | 100% | correct (enpara-fee70191-review3) |
| `str3.qa_no_faqpage` | 1 | 0 | 1 | 0 | 0 | 0% | wrong (enpara-fee70191) |
| `str3.unparsed` | 3 | 3 | 0 | 0 | 0 | 100% | correct (enpara-fee70191-review3) |
| `str5.names` | 2 | 0 | 2 | 0 | 0 | 0% | wrong (enpara-fee70191) |
| `str7.over_100kb` | 2 | 2 | 0 | 0 | 0 | 100% | correct (enpara-fee70191-review3) |
| `str8.headers` | 1 | 1 | 0 | 0 | 0 | 100% | correct (enpara-fee70191) |
| `str9.no_return` | 2 | 2 | 0 | 0 | 0 | 100% | correct (enpara-fee70191-review3) |
| `str9.status` | 2 | 2 | 0 | 0 | 0 | 100% | correct (enpara-fee70191-review3) |
| `tseo1.head_closed_later` | 3 | 0 | 3 | 0 | 0 | 0% | wrong (enpara-fee70191-review3) |
| `tseo1.head_closed_lost` | 3 | 0 | 3 | 0 | 0 | 0% | wrong (enpara-fee70191-review3) |

Cards reviewed: 43; correct 22, wrong 12, wording 2, incomplete 7 (51% correct).
