# Packet boundary detector + split report — design

**Date:** 2026-07-13
**Status:** approved (pending spec review)

## Context

The real CTV submission (`FA-PM260226080.pdf`) is a **262-page, fully scanned
PDF** — every page is a single A4 raster image with **zero text layer**. Its
structure, confirmed by scanning all pages as contact sheets:

- **p1–2** — master payment summary (bảng thanh toán CTV), rotated.
- **p3–7** — official *Bảng kê 01/TNDN* (mua vào không có hóa đơn), VNG, ending
  in signatures.
- **p8 → end** — ~31–33 repeating **per-CTV packets**, ~7–9 pages each, every
  packet led by a "HỢP ĐỒNG DỊCH VỤ" service-contract cover, followed in a
  stable order by contract body pages, a biên bản, a rotated appendix page, and
  a boxed form page.

Because there is no text layer, boundaries cannot be found by grepping embedded
text. The structure is, however, highly regular and visually templated, and a
**structured roster already exists** as a clean spreadsheet
(`BẢNG KÊ THANH TOÁN CTV -THÁNG 2.2026.xlsx`, ~33 rows), so reconciliation needs
no OCR.

This slice is the "one giant scan → per-CTV folders" step that precedes the
existing reviewer. It is a throwaway prototype slice: prove the cuts are right.

## Goal

Split the 262-page scan into per-CTV packets by detecting the recurring
contract-cover page, reconcile the result against the Excel roster, and emit a
visual report to verify the boundaries by eye. No OCR, no GPU.

## Non-goals

- No field extraction / OCR of values (that is a later stage; boundaries only).
- No wiring into the reviewer app yet (no `manifest.json` output this slice).
- Per-page type labels are best-effort, not a focus.
- Not production-hardened; tuned against this one submission.

## Approach

### Stage 1 — Boundary signal: auto-derive the recurring cover, then cut

Each packet opens with a visually distinctive cover (in this submission, a
centered "HỢP ĐỒNG DỊCH VỤ" title above a two-column "BÊN A / BÊN B" block).
**Nothing about the specific page numbers, threshold, or reference layout is
hardcoded** — the cover is discovered from the file itself:

1. Render each page to a low-DPI grayscale image (PyMuPDF); take each page's top
   **band** (top ~25%), resized to a common size so bands are comparable.
2. Compute pairwise similarity across all top-bands (`cv2.matchTemplate` /
   normalized correlation) and cluster them. In a stack of repeating packets the
   cover band recurs ~N times near-identically, forming the **largest recurring
   cluster**; that cluster is the set of covers, and its medoid is the derived
   template. Body/biên bản/form/appendix pages are visually varied and do not
   form a comparably large tight cluster.
3. The cut points are the cover pages (cluster members), in order. The
   separating **threshold is the natural gap** between the cover cluster's
   similarity and the rest — computed from the distribution, not a constant.
4. **Preamble is derived, not fixed:** every page before the first detected
   cover is front matter (the summary + bảng kê here). A file with a longer,
   shorter, or absent preamble is handled with no change.

Optional override: a caller may pass one known cover (page + band) to seed the
template instead of auto-deriving it — useful if a submission's covers vary too
much to cluster cleanly.

### Stage 2 — Reconcile against the roster (guardrail)

1. Read `BẢNG KÊ THANH TOÁN CTV -THÁNG 2.2026.xlsx` with openpyxl → an ordered
   list of N collaborators (name; other columns kept for later stages).
2. Compare detected cover count to N.
3. Align packet *i* → roster row *i* by order.
4. Flag a boundary **low-confidence** when any of: its cover score is near the
   threshold; the packet length departs from the ~8-page norm (configurable
   band, e.g. outside 5–12); or the total count ≠ N.

The roster is treated as ground truth for the *count and order*, so the report
can state "N found / N expected ✓" or point at the specific gap to check.

### Stage 3 — Coarse per-page type labels (light)

Reference-crop template match of each page against the ~5 layouts that repeat
every packet (cover / contract-body / biên bản / rotated-appendix / form),
using reference crops taken from the first complete packet. Emitted as chips in
the report; best-effort, not relied upon for boundaries.

### Stage 4 — Output: self-contained HTML split report

A single HTML file (thumbnails embedded as data-URIs) containing:

- A summary banner: packets found vs roster N, alignment status, count of
  low-confidence boundaries.
- One card per packet: cover-page thumbnail, page range (e.g. `p8–15`), aligned
  CTV name, page count, per-page type chips, and a green/amber confidence badge.

## Data flow

```
PDF (any # of scanned pages)
  → render pages (grayscale, low DPI)                     [PyMuPDF]
  → page top-bands → pairwise similarity → cluster        [cv2 / numpy]
  → largest recurring cluster = covers; medoid = template
  → derived threshold (gap); first cover ends the preamble
  → packets [{start,end,cover_score,pages}]
  → reconcile with roster rows                            [openpyxl]
  → packets + name + confidence flags
  → HTML split report (data-URI thumbnails)               [PIL]
```

## File layout

- `splitter/detect_packets.py` — new. Rendering, scoring, boundary decision,
  reconciliation, report generation. Reads paths via CLI args / constants.
- `splitter/detect_packets_test.py` — new. Pure-logic tests on the
  cut/reconcile step (score array + expected count → boundaries + flags),
  matching the project's "pure-logic tests only" convention. No PDF needed.
- `splitter/README.md` — extend with how to run and the PII note.

Code contains **no PII** and is committable. The **report and all thumbnails
contain real PII and are written to the scratchpad only, never committed.**

## Testing & verification

- Unit: pure-logic boundary/reconcile function tested on synthetic score arrays
  (clear covers, near-threshold cover, missing cover, extra cover) → asserts
  correct cut indices and confidence flags.
- End-to-end: run against the real PDF; expect ~33 packets, regular spacing,
  covers aligned to roster names in order, report renders and opens. The report
  is the human-verifiable proof.

## Risks & mitigations

- **Cluster/threshold fragility** — if covers vary too much, the recurring
  cluster could be loose or a stray page could sit near the gap. Mitigation: the
  threshold is the derived distribution gap (not a constant); the roster
  count/order cross-check catches an off-by-one; near-threshold pages are flagged
  amber rather than silently cut; and a caller can seed a known cover template as
  an override.
- **No dominant cluster** — a submission that is *not* a stack of repeating
  same-template packets (heterogeneous one-off docs) won't produce a clear cover
  cluster. Mitigation: detect this (no cluster meaningfully larger than the rest)
  and report it rather than emit garbage cuts; that case needs the later
  OCR/type-classifier route, out of scope here.
- **Variable packet length** — contracts are 4–5 pages, so packet size varies.
  Mitigation: boundaries come from cover detection, not fixed spacing; length is
  only a confidence signal, not a cut rule.
- **Rotated pages** — some pages are landscape/rotated. Mitigation: cover
  detection uses the (portrait) contract cover; rotated appendix pages are not
  covers and score low.

## Generality

The 262-page / ~33-CTV file is only a sample. Nothing in the algorithm is keyed
to those numbers:

- **Page count** — any; pages are processed as a stream.
- **Packet count** — whatever the recurring-cover cluster contains, validated
  against the roster's N (also read from the file, not assumed).
- **Preamble length** — derived (pages before the first cover); 0, 7, or more.
- **Packet length** — variable; boundaries come from covers, not fixed spacing.
- **Threshold / reference cover** — derived from the file, not constants.

**The one assumption:** the submission is a stack of *repeating same-template
packets* — which is what these monthly CTV packs are. The same code handles a
smaller or larger pack of the same shape unchanged. A genuinely different
submission format re-derives its own cover template automatically (or accepts a
one-page seed); a non-repeating pile of heterogeneous docs is explicitly out of
scope and is detected and reported rather than mis-cut.

## Success criterion

Running on the real PDF yields the roster's number of packets, boundaries at the
contract covers, packets aligned to the correct collaborator names in order, and
a report that makes any low-confidence cut obvious. No PII committed.
