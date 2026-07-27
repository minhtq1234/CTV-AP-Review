# Review Currency Formatting Design

**Date:** 2026-07-27  
**Status:** Approved interaction design; awaiting written-spec review

## Goal

Display financial values from the Excel roster in a reviewer-friendly Vietnamese
currency format. For example, the raw value `6111111` should render as
`6.111.111 ₫`.

## Scope

Formatting is presentation-only. It applies when a review field has both:

- group `Thanh toán`; and
- kind `number`.

The same formatted value appears in:

1. the left-side `Kê khai (Excel)` field row; and
2. the blue roster-value callout attached to the document bbox.

Identity numbers, tax IDs, account numbers, dates, names, invoice numbers, and
other non-financial values retain their existing display.

## Data and Comparison Behavior

The manifest value, backend response, saved review, and comparison inputs remain
unchanged. A pure frontend presentation helper receives the field metadata and
raw expected value, then returns display text.

For eligible financial values, the helper:

1. removes existing grouping separators, whitespace, and an optional VND/`₫`
   suffix;
2. parses the remaining integer digits;
3. formats the integer with the `vi-VN` locale; and
4. appends ` ₫`.

Already formatted financial values normalize to the same output. Empty or
unparseable values fall back to their original text so the UI never invents a
number.

## Component Integration

`FolderFieldsPanel` uses the helper for `Kê khai (Excel)`. `FolderReview`
formats the selected field through the same helper before passing
`rosterValue` to `EvidenceViewer`. `EvidenceViewer` remains a display-only
consumer and needs no currency-specific logic.

This keeps formatting policy centralized and ensures the row and callout cannot
drift.

## Testing

Tests are written and observed failing before production changes.

- Pure formatting tests cover raw digits, existing separators/currency suffixes,
  zero, invalid text, and a non-financial numeric field.
- Component tests verify the field row displays `6.111.111 ₫`.
- Review presentation tests verify the selected field passes the same formatted
  value to the document callout without changing comparison behavior.
- The complete frontend suite, backend suite, production build, and browser QA
  run before completion.

## Non-Goals

- No backend or manifest normalization.
- No OCR changes.
- No currency conversion or decimal support.
- No changes to comparison, review state, reports, packet status, or persisted
  data.
