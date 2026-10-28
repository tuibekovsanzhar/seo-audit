# w6-media: P1, media on the pages that matter (2026-10-22)

Source: a live comparison between a hand-made audit of a Ticimax shop (1 Oct) and Maya's report (22 Oct). The plan
that lists every blind spot is `seo_audit/maya-audit-kor-nokta-plani.md` (P1-P5). This is P1. Decision: DECISIONS 249.

## What was missed, and why

| Missed live | Cause in the code |
|---|---|
| Three homepage banners of 1.1-1.8 MB (two PNGs named .jpg) | `media_sample.image_sample` put the homepage's first 3 images and its largest *declared* images first; lazy banners further down declared no size, and the 30-image sample filled up page by page |
| A 10.3 MB promo video | It is named only in the homepage's VideoObject `contentUrl`; a script inserts the player on scroll, so the render never asked for it. It is also on the platform CDN, which the video check treated as another site |
| A 200 × 200 share image | `og:image` redirected (301) to the platform CDN; redirects were followed on the same origin only. And 200 × 200 is not under the 200 px minimum |

## Changes

- `config.py`, `cli.py`: `key_image_checks_max` (40; `FAST_KEY_IMAGE_CHECKS_MAX` 15 in a fast check).
- `media_sample.py`: `image_sample` pins every image the homepage and the key pages show or preload before the sample;
  `key_image_limit`; `video_sources` (`<video>`/`<source>` src or data-src, VideoObject contentUrl naming a video
  file); `size_video` shared by the markup and the render paths, using the asset-host test; `own_image` no longer
  treats another port on the same IP as the same site.
- `analysis.py`: `<video data-src>` and `<source data-src>` are read.
- `structure_data.py`: og:image on the asset host is asked directly; `_follow_og_image` follows a redirect to the asset
  host (reading that host's robots.txt first); `_check_videos` uses `video_sources` and `size_video`.
- `other_sites.py`: same sample as `structure_data`; an og:image on the asset host is not queued as another site.
- `checks/structure.py`: video evidence carries `found_by`, with a note when the file is known only from contentUrl;
  STR-10 Info "share image smaller than 600 × 315 pixels (shown as a small thumbnail)".
- `maya_audit_web/wording.py`, `locales/findings/tr.json`: the new title, fix, expectation and notes in Turkish.

## Tests

`tests/test_p1_media.py`, 9 tests; 7 fail on the code before this change, the 2 "must not" tests pass on both:

- a lazy banner with no declared size, 6th on the homepage, sample of 4: measured, S3, PNG-as-.jpg noted;
- key images have their own cap on top of the sample; nothing is asked when `image_checks_max` is 0;
- small homepage images are measured and not reported;
- a video named only in VideoObject on the asset host is sized (`found_by: structured_data`, note present);
- `<source data-src>` is sized;
- a VideoObject pointing at a watch page or another site is not downloaded;
- a share image redirected to the asset host is read; 200 × 200 is the Info note, not the S4;
- a 1200 × 630 share image is not noted; a 120 × 120 one stays S4 and is not double-noted.

`tests/test_preview16_measure.py::test_fast_check_sends_the_reduced_counts` now uses 30 homepage images: 30 in a full
audit, 15 + 10 in a fast check. `docs/FIXTURE-MATRIX.md` regenerated.

## Live re-run (arjava.com.tr, 100 pages, delay 1 s, Firecrawl off)

| | Before | After |
|---|---|---|
| Images over 500 KB | 2 (S4) | 6 (S3): the three banners, a 2.53 MB product image the hand audit also missed, and the two found before |
| PNG served as .jpg | not seen | 2 (Info) |
| 10.3 MB video | not seen | S4, `found_by: structured_data` |
| 200 × 200 share image | og:image not assessed | Info on 4 pages |
| `image_status` / `video_size` requests | 30 / 0 | 43 / 1 |

## Open

- CSS background images are still not sized (not in the analysis).
- Whether the Info threshold for share images (600 × 315) should be S4 is the owner's call.
