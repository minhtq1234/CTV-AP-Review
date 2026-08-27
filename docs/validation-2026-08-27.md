# Validation pass — 2026-08-27

First time the tool's output has been checked against the scans rather than against itself.
Method: `server/findings_worksheet.py` renders every OCR-sourced claim beside a crop of the
page at the bbox the tool recorded, with that box outlined. 48 claims over packets
0, 3, 24, 34, 39 of the July batch, plus 9, 31, 35 (the high-confidence name disagreements),
then a batch-wide count over all 41.

**Headline: 4 of 41 packets carry a false `no`.** `no` drives `cần gửi lại`, so the tool would
send four valid packets back to the CTV. Both causes are extraction defects, and neither is
visible to the tool itself.

## 1. `group_lines` has no notion of columns

Root cause of three of the four. Contracts and BBNTs end in a **two-column signature block**:

    Họ và tên: Trần Văn Tiến        |    Họ và tên: Hoàng Nguyễn Hải Đăng
    (VNG's signatory)                    (the CTV — the one the roster names)

`group_lines` clusters words by y across the full page width, so both parties' labels and
names land on one "line". The name matcher then takes the first match on it — the left
column — and the bbox spans whatever matched, sometimes crossing the divider.

| packet | tool read | roster | what the crop shows |
|---|---|---|---|
| 9 | `Trần Lê Hoài Anh` @ 0.96 | `Nhan Kiến Phát` | box on the LEFT column of the block |
| 31 | `Trịnh Đức Minh` @ 0.94 | `Phan Tấn Tài` | box on the LEFT column; the BBNT's correct name is boxed elsewhere and read as `''` |
| 35 | `Văn Họ` @ 0.96 | `Hoàng Nguyễn Hải Đăng` | box spans `Văn Tiến` (left name) **across the divider** to `Họ` (right column's LABEL) |

In every case **every identity number matches the roster exactly** — CCCD, MST, account,
date — and the attached CCCD card confirms the person. So these are not mis-splits; the
packets are correctly matched and only the name is wrong.

Packet 9 has a second, independent defect: its BBNT name reads `Nhan Kiến`, the correct name
**truncated** from three tokens to two.

## 2. Confidence measures legibility, not correctness

`_search_line` sets confidence to `min(word conf)/100`, i.e. how crisply the glyphs printed —
not whether the right words were grouped. A box spanning two columns of clean print scores
0.96. Batch-wide over all 41 packets:

| status × confidence | count |
|---|---|
| disagreement, ≥ `LOW_CONF` | **8** |
| disagreement, < `LOW_CONF` | 6 |
| agreement, ≥ `LOW_CONF` | 262 |
| flagged `rv`, < `LOW_CONF` | 64 |

Packet 34 is the sharpest case — the same digits on the same page, read two ways:

- CCCD on Hợp đồng → `070198011354` @ **0.93** (wrong)
- CCCD on BBNT → `070198011354` @ **0.90** (same wrong value)
- MST on Hợp đồng → `079198011354` @ 0.86 (**correct**; the page reads this)

And packet 39 read a date correctly at **0.06**.

Consequences: **agreement across documents is not independent corroboration** (the same
misread repeats on two documents of similar scan quality, so `_compare_reads` treating copies
as corroborating is unsafe), and **the `LOW_CONF` escalation trigger structurally cannot see a
confidently-wrong read**.

## 3. Position markers that land on prose — 4 of 48

All report `pending`/`''` honestly, so no false verdict; but they send the reviewer to the
wrong place, which is the one thing "locate & look" must get right.

| claim | box lands on |
|---|---|
| p0 `Số tài khoản` / Hợp đồng | *"ngân hàng của Bên Cung Ứng Dịch"* — prose containing "số tài khoản" |
| p0, p34 `Gross` | *"Chỉ tiêu xét phí dịch vụ thanh toán:"* and the `ĐIỀU 2` heading |
| p34 `Họ và tên` / BBNT | an empty signature line |
| p24 `MST` / Hợp đồng | the value beside **"TK số"** — the wrong field's label, read as MST @ 0.91 |

`_is_labeled_anchor` exists for exactly this and is used by `find_name`, but `locate_field`
does not apply it.

## 4. A pattern that rejects a legible value

Packet 9's date is plainly `26/06/ 1984` on the page and reads `''`, because the stray space
breaks `DATE = \d{1,2}/\d{1,2}/\d{4}`. Same family as `MONEY` needing a separator.

## What is working

- **262 high-confidence agreements** batch-wide. Every name, CCCD, MST, account and date
  checked on packets 0, 3, 24, 39 matched the scan.
- The `phi` lookahead fix (`b7e2994`) is visibly right on real pixels — `8.888.889` boxed on
  `2.1. Phí dịch vụ:`.
- The CCCD card reads are correct wherever a card was attached, and they are what proves
  §1's three packets are correctly matched.
- Where the tool cannot read, it says so and still marks a position — the design intent holds.

## Fix order

1. **Column-aware line grouping.** Fixes three false `no`s and the crossing-divider bbox.
   Split a line at a large x-gap before matching, or match per column.
2. **Apply `_is_labeled_anchor` in `locate_field`.** Fixes §3 — an anchor inside running prose
   should not produce a hit at all.
3. **Stop presenting confidence as reliability** anywhere in the UI, and do not add a gate
   that depends on it. A digit-level difference against an otherwise-consistent roster value
   is a better misread signal.
4. **Tolerate whitespace in `DATE`** (and audit the other patterns for the same).

Not fixed here, deliberately: this pass was measurement. Every item above is evidenced by a
crop in the worksheet, which stays on the workstation (`server/data/worksheets/`, gitignored —
it embeds real names, CCCD numbers and scan images).
