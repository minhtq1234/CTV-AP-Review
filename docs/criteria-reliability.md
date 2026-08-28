# Which criteria are reliable enough to show

Measured 2026-08-27 on case `68ddc1f0` (July, 41 packets, name fix + IDP cards).
Counts are **cells**, not criterion rollups — see the warning below.

## Read the rollups with care

At criterion level only **3 of 25** ever produce both a pass and a finding (#5, #7, #15).
That is misleading. In `criteria._SEVERITY` **`pending` outranks `ok`**, so one unevaluated
cell suppresses a pass for the whole criterion. #1 Họ và tên has **115 `ok` cells** and still
rolls up to `pending` on 38 of 41 packets.

Cell totals across the batch: **663 ok · 24 no · 351 rv · 111 missing · 1188 pending · 123 na**
— the engine actually decides **687 of 2460 cells (28%)**.

So demo the **matrix**, not the criterion list. The matrix shows where the engine decided; the
list mostly shows where it didn't.

## Tier 1 — decides at scale, and hand-checked

| # | criterion | ok | no | decides against |
|---|---|---|---|---|
| 2 | Số CCCD/Passport | 127 | 6 | Excel, Hợp đồng, BBNT, CCCD card |
| 1 | Họ và tên | 115 | 0 | Excel, Hợp đồng, BBNT |
| 7 | Số tài khoản | 89 | 2 | Excel, Hợp đồng, BBNT |
| 14 | Gross (Hợp đồng/BBNT/Bảng Kê) | 77 | 0 | Excel, Hợp đồng, BBNT |
| 5 | MST cá nhân | 66 | 1 | Excel, Hợp đồng |
| 3 | Ngày sinh | 59 | 1 | Excel, Hợp đồng |

These are the ones the validation pass covered. Two known false results remain:

- **#2 on packet 34** — a confident double misread, `070198011354` for `079198011354` at 0.93
  and 0.90. Avoid that packet.
- **#5 on packet 24** — the MST anchor read the value beside "TK số", the wrong field's label.

#3 used to carry 17 `rv` here because handwritten dates that already matched the bảng kê were
downgraded for a low-confidence read. `compare_values.compare` no longer does that -- confidence
is `min(word confidence)`, legibility rather than correctness, so an outright match now passes
at any confidence (`docs/handoff-ver3.md`). Re-running this measurement after that fix: all 17
move to `ok`, and nothing else on this case moves at all.

## Tier 2 — arithmetic on the bảng kê, always passes

| # | criterion | result |
|---|---|---|
| 16 | Net | 41/41 ok |
| 17 | Công thức Gross − PIT = Net | 41/41 ok |
| 4 | Giới tính Nam/Nữ | 41/41 ok |

Worth showing as "the totals reconcile", but be honest that these compare the **roster against
itself** — they are not document verification. #4 in particular checks one Excel column and
nothing else, so it demonstrates almost nothing.

## Tier 3 — correctly handed to the reviewer (a feature, not a gap)

| # | criterion | result |
|---|---|---|
| 21, 22, 23, 24 | signatures & seals on Hợp đồng / BBNT | 41 `rv` each |
| 28 | Bảng Kê signature & company seal | 41 `rv` |
| 6 | Trạng thái MST | 39 `rv` (needs the tax website) |
| 18, 25 | Cam kết / Phụ lục when applicable | `na` where not applicable, else `rv` |

`rv` is the **right** answer here — a signature is a judgement only a person makes. Show these
as the tool routing work to the reviewer rather than guessing.

## Tier 4 — do not show, nothing is extracted

**Every cell `pending`:** #8 Thông tin ngân hàng · #12 Thời hạn dịch vụ · #27 Thông tin công ty
VNG. And #9 Nội dung dịch vụ · #10 Ngày bắt đầu · #11 Ngày kết thúc · #13 Thời hạn & phương
thức thanh toán are `missing` on 21 packets and `pending` on the rest — never decided.

Seven criteria with no output at all. Opening one in the demo shows an empty row.

## #15 PIT — mostly right, with a known false class

A rule, not a comparison: PIT = 0 requires a cam kết or an exemption basis. 7 `ok`, 14 `no`,
and **14 of the batch's 20 `no` packets come from this one criterion**, so it deserves scrutiny.

| Gross | PIT | packets | verdict |
|---|---|---|---|
| exactly 2,000,000 | 0 | 11 | **genuine** — at/above the withholding threshold, no cam kết |
| 3,250,000 / 3,750,000 | 0 | 2 | **genuine** |
| 1,000,000 | 0 | p27, p31 | **FALSE** — below threshold, so PIT = 0 is lawful |

The 7 `ok` packets all sit at 3.25M–8M with a commitment present. So the engine applies the
commitment half of its own rule but **not the threshold half**, though its `how` text names
both. Fix: skip the finding when Gross is below the withholding threshold.

Safe to show on a packet at 2,000,000 or above. Avoid p27 and p31 for this criterion.

## Shortest honest demo

Open a Tier 1 criterion in the matrix, show a decided cell and its located evidence on the
scan, then show a Tier 3 signature row as work the tool deliberately hands over. That is a
true account of what exists: **six criteria that reconcile documents against the bảng kê, six
that route judgement to a person, and seven that are not built yet.**

## Document segmentation — sound structurally, imperfect semantically

Measured on the same 41 packets.

**What is solid.** No page is lost or double-counted: `sum(doc pages) == n_pages` on **41 of
41**. Coverage cross-checks against three independent surfaces — `id_front`/`id_back` on 40
packets matches `CCCD: 40 đã gắn`; `appendix` on 20 matches criteria #9–#13 being `missing` on
exactly 21 (= 41−20); `commitment` on 7 matches both `hasCommitment` and #15's 7 `ok`.

**What is wrong.** 16 of 41 packets (39%) carry the same document label twice, and the page
counts show these are not genuine duplicates:

- **A BBNT split in two** — the `[1, 2]` signature on p2, p22, p23, p24, p27, p31, p33. One
  3-page biên bản broken into a 1-page and a 2-page document. A real second BBNT would not
  reliably be 1-page-then-2.
- **A 1-page contract followed by a 3-page `Tra cứu thuế`** (p8, p15, p16, p30, p32, p35, p38).
  Contracts run 3–4 pages, so the contract's body pages are being classified as a tax lookup.

**Why it does not bite today.** Packets with a 1-page contract score the same as the rest:

| | ok | no | pending | missing |
|---|---|---|---|---|
| contract ≥3 pages (34 packets) | 3.1 | 0.6 | 9.1 | 2.7 |
| contract <3 pages (7 packets) | 3.4 | 0.6 | 9.7 | 2.7 |

Because every Tier 1 field — name, CCCD, MST, account, date, fee — sits on the contract's
**first** page, which is always present, and the criteria that would need the body pages
(#9–#13) are the ones not built.

**When it will bite.** The moment #9–#13 are implemented: Nội dung dịch vụ, the start/end
dates and the payment terms live in the contract body, and on those 7 packets those pages are
labelled `Tra cứu thuế`. Likewise the signature criteria (#21–#24) route to a named document,
so a BBNT split in two makes "the BBNT" ambiguous. Fix segmentation before building either.
