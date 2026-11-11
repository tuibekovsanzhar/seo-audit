# Expert review accuracy by rule

Made by `scripts/expert_accuracy.py` from `enpara-2e5829fb.json`, `enpara-fee70191.json` (DECISIONS 338, 340). A card's verdict counts once for each rule on it; "wrong" is the expert's verdict, before the evidence was checked (each review file says what the evidence showed and what was fixed).

| Rule | Cards reviewed | Correct | Wrong | Wording | Incomplete | Share correct | Latest |
|---|---|---|---|---|---|---|---|
| `acc2.blocks.sample` | 1 | 0 | 1 | 0 | 0 | 0% | wrong (enpara-2e5829fb) |
| `acc8.redirecting` | 2 | 0 | 0 | 0 | 2 | 0% | incomplete (enpara-fee70191) |
| `idx1.4xx.referenced` | 1 | 0 | 0 | 0 | 1 | 0% | incomplete (enpara-2e5829fb) |
| `idx1.4xx.sitemap_only` | 1 | 0 | 1 | 0 | 0 | 0% | wrong (enpara-fee70191) |
| `idx2.temporary` | 1 | 0 | 1 | 0 | 0 | 0% | wrong (enpara-2e5829fb) |
| `idx6.links_to_redirect` | 2 | 1 | 0 | 1 | 0 | 50% | wording (enpara-fee70191) |
| `str14.no_text` | 2 | 2 | 0 | 0 | 0 | 100% | correct (enpara-fee70191) |
| `str16.shared` | 2 | 2 | 0 | 0 | 0 | 100% | correct (enpara-fee70191) |
| `str2.no_h1` | 2 | 1 | 0 | 1 | 0 | 50% | correct (enpara-fee70191) |
| `str2.no_subheadings` | 1 | 0 | 1 | 0 | 0 | 0% | wrong (enpara-2e5829fb) |
| `str2.styled_subheadings` | 1 | 1 | 0 | 0 | 0 | 100% | correct (enpara-fee70191) |
| `str3.qa_no_faqpage` | 1 | 0 | 1 | 0 | 0 | 0% | wrong (enpara-fee70191) |
| `str3.unparsed` | 2 | 2 | 0 | 0 | 0 | 100% | correct (enpara-fee70191) |
| `str5.names` | 2 | 0 | 2 | 0 | 0 | 0% | wrong (enpara-fee70191) |
| `str7.over_100kb` | 1 | 1 | 0 | 0 | 0 | 100% | correct (enpara-fee70191) |
| `str8.headers` | 1 | 1 | 0 | 0 | 0 | 100% | correct (enpara-fee70191) |
| `str9.no_return` | 1 | 1 | 0 | 0 | 0 | 100% | correct (enpara-fee70191) |
| `str9.status` | 1 | 1 | 0 | 0 | 0 | 100% | correct (enpara-fee70191) |
| `tseo1.head_closed_later` | 2 | 0 | 2 | 0 | 0 | 0% | wrong (enpara-fee70191) |
| `tseo1.head_closed_lost` | 2 | 0 | 2 | 0 | 0 | 0% | wrong (enpara-fee70191) |

Cards reviewed: 28; correct 13, wrong 9, wording 2, incomplete 4 (46% correct).
