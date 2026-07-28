# CCCD OCR Adapter Reliability Fix

## Goal

Make the local CCCD OCR adapter recognize usable front/back evidence from
real workbook images without weakening the existing exact-only automatic
attachment rules.

The current Tesseract engine is healthy: on the real 61-image workbook,
direct OCR found 22 exact roster CCCD values, including 17 at confidence
`>= 0.85`. The adapter still returned zero because it requires idealized
marker phrases and a correctly recognized `Số` label before it will retain
a number.

## Safety constraints

- Automatic placement remains limited to an exact, unique 12-digit roster
  CCCD with OCR confidence `>= 0.85`.
- The roster identity must still resolve to exactly one processed packet.
- Competing candidates, duplicate identities, incomplete front/back pairs,
  low-confidence reads, and ambiguous geometry remain unresolved.
- Names remain suggestions only and never become automatic attachment keys.
- No external OCR service and no PII leaves the local workstation.

## OCR behavior

### Number-region recovery

Keep the existing label-anchored number locator as the first choice.

If it fails, accept a full-image OCR word as a fallback region only when:

- the word contains exactly 12 digits after removing separators;
- the word has a real bounding box from Tesseract; and
- there is exactly one such candidate at the best confidence.

Re-OCR the recovered bounding box with the existing digits-only crop. The
crop result, not the initial full-image token, supplies the final number and
confidence. Multiple competing 12-digit regions remain unresolved.

This is still a located region. The adapter does not scan arbitrary digit
runs or select dates, MRZ substrings, or the "best-looking" number.

### Side classification

Keep exact marker groups as the strongest signal, then add two structural
fallbacks:

- A card is a front when it has a unique recovered 12-digit number region
  plus at least one front marker group.
- A card is a back when OCR contains a strong CCCD MRZ signature or a strong
  back marker group.

Conflicting front/back signals return `unknown`.

### Pairing and matching

The existing same-sheet, mutual-nearest, margin-checked front/back pairing
remains unchanged. The existing exact-only resolution, competition checks,
packet-target checks, atomic attachment, and rollback behavior remain
unchanged.

## Tests

Add regression tests before production changes:

- A real-shaped front OCR result where `Số` is misread but a high-confidence
  12-digit word is present produces a number region and final CCCD.
- Multiple 12-digit candidates do not produce a fallback region.
- Dates and non-12-digit tokens do not produce a fallback region.
- A recovered number plus a front marker classifies as front.
- An MRZ signature classifies as back.
- Conflicting structural signals remain unknown.
- Existing exact-marker, missing-label, and digits-elsewhere protections
  continue to pass.

## Acceptance

After automated tests pass, rerun `CCCD_T2.xlsx` against the existing
32-packet case inputs. Confirm:

- at least one safe front/back candidate attaches automatically;
- every attachment uses an exact unique 12-digit roster identity;
- unresolved images remain visible in the compact CCCD summary;
- attached packets show CCCD front/back document tabs and A1 routes to the
  attached front image; and
- the complete backend, frontend, and production build verification remains
  green.
