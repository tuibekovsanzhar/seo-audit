# Shared severity policy

`maya_audit/severity.py` owns the final policy for native audits, provider-content replacement, report construction
and explicit saved-evidence reassessment. Checks still declare the maximum impact their particular subtype supports;
the common policy never promotes that declaration. Original severity and all inputs remain in
`finding.evidence.severity_assessment`. Observation confidence, inferred cause and business impact are different claims.

The owner requested **impact × reach × certainty**. These are ordinal priority weights, not measured probabilities
or a calibrated business-loss model. Do not advertise an accuracy percentage or guaranteed search impact from them.

| Factor | Values | Source/limits |
|---|---|---|
| Impact | S1=4, S2=3, S3=2, S4=1, Info=0 | Maximum declared by the individual check/subtype, using the definitions below |
| Reach | 3: homepage, explicitly audited start URL or confirmed key page; 2: >=half the check's actually assessed content population; 1: other or unestablished reach | Discovered/sitemap URLs do not enlarge a content denominator. Unknown reach is not zero. |
| Certainty | verified=3, inferred=2, estimated=1, not assessed=unavailable | Confidence concerns the observation. It does not prove cause, harmful impact or owner intent. |

Product thresholds: >=12 S1, >=9 S2, >=2 S3, >0 S4, zero impact Info. Apply the source-impact ceiling afterward.
Unavailable certainty retains a diagnostic ceiling of Medium, not a pass. Estimated or wholly hypothetical conclusions
are at most Medium. Contradictory/diagnostic/unassessed judgments are at most Medium. Supported cosmetic issues in a
shared template become Notes; a repeated location by itself is **not** evidence of cosmetic impact. Real functional,
retrieval and accessibility failures remain eligible for their supported severity. No finding is deleted by this policy.

## Maximum-impact contract per check

Within each row, the subtype's source finding declares the actual supported maximum. The check code alone cannot
justify its highest possible impact. Source constructors and evidence remain reviewable; this table is not a new rule engine.

| Check(s) | Supported impact and boundary |
|---|---|
| INT-1..4 | Integrity gates and coverage/politeness, not an extra severity-ranked website defect |
| ACC-1 | Robots retrieval availability; actual observed access failure versus inconclusive retrieval |
| ACC-2 | Measured crawler restrictions, qualified by private/utility scope and owner intent |
| ACC-3 | Index/snippet directives; intentional noindex is not automatically harmful exclusion |
| ACC-4 | Client/UA response differences; missing or failed baseline cannot establish bot-specific blocking |
| ACC-5 | Supplied real-crawler logs; unassessed thresholds are observations |
| ACC-6 | Training-policy observations, without duplicating search restrictions |
| ACC-7 | Observed robots crawl-delay and request scope, not business loss |
| ACC-8 | Supplied llms.txt resource/link evidence; unconfirmed access remains diagnostic |
| ACC-9 | Observed automated-client blocks/challenges; client and response scope required |
| IDX-1 | Observed HTTP/empty/transport failures; repeated versus single and key-page scope remain explicit |
| IDX-2 | Completed certificate/HTTP-to-HTTPS evidence per host; missing assessments are unknown |
| IDX-3 | Proven cycles can remain critical; cookie/intermittent/incomplete checks are distinct |
| IDX-4 | Actual canonical values and comparable targets; similarity/owner intent remain qualified |
| IDX-5 | Sitemap membership/status/indexability by URL; overlapping retrieval repairs count once |
| IDX-6 | Source/target link failures with methods/corroboration, not HEAD-only deletion claims |
| IDX-7 | Assessed discovery/depth, not proof that unassessed pages cannot be discovered |
| IDX-8 | Comparable content/purpose, retaining meaningful variants and legitimate consolidation |
| IDX-9..10 | Actual supplied search-console evidence; unavailable provider measurements are not zero |
| RND-1..3 | Raw/rendered/interaction evidence; unrendered heuristics at most Medium |
| RND-4 | Supported non-text/accessibility evidence; embedding alone is informational |
| RND-5 | Supported content walls versus expected account/utility controls |
| RND-6..7 | Measured payload/content delivery properties, conditional recommendations |
| STR-1..2 | Actual title/heading properties; editorial bands/hierarchy do not prove ranking penalties |
| STR-3..5 | Supported structured-data/visible-value/entity consistency; alias/translation context preserved |
| STR-6 | Same-entity/event date comparisons, not legitimate publication/modification differences |
| STR-7..8 | Contextual image/table semantics; uncertainty and equivalent descriptions retained |
| STR-9 | Recorded locale/alternate annotations and assessed reciprocal evidence |
| STR-10..11 | Actual share/resource/technology observations; preview guarantees are unsupported |
| STR-12..13 | Language/template/invisible-character evidence; heuristic classifications at most Medium |
| STR-14..15 | Contextual link wording/content properties; generic structure alone does not prove harm |
| STR-16..17 | Description/archive/content comparisons, preserving distinct purposes |
| STR-18..23 | Their measured metadata/content/structural subtypes, retaining existing limits and owner context |
| TSEO-1 | Recorded technical markup; cosmetic/hygiene notes do not become severe through repetition |
| PRF-1..3 | Native timings/reliability or available lab/field performance; missing data and causes remain unknown |
| ANS-1..5 | Separate answer-evidence panel, not duplicated site problems or invented AI access |

Source declarations are not immutable truth: changing one still requires evidence, a contrasting retained case and
the judgment-validator review. A confidence cap cannot substitute for correcting a false observation. In particular,
the benchmark's colour-variant and A-to-Z language false alarms remain failures until their actual classifications change.
