# Handoff — starting ver 3

Written 2026-08-27 at `01b30b9`. Read this first, then §"What to work on".

## Where you are

    checkout   /Users/lap16603/Documents/New project/work/CTV_APReview-stable
    branch     stable/2026-08-25-cccd-idp
    tests      775 server (pytest, server/), 239 frontend (vitest), tsc -b clean

**There are THREE divergent lineages** and they share filenames with different APIs:

| lineage | has |
|---|---|
| `ver1` @ `9aa66b8` | table list, grid detail, `BoundaryReviewScreen`. 213 commits divergent |
| `main` @ `18a62b6` | `server/checklist.py`, `ChecklistPanel.tsx`, `review.ts` with `review.items` |
| **`stable`** (this one) | criteria engine, Tổng hợp, overrides. No `checklist.py`, no `ChecklistPanel.tsx`, `review.ts` uses `review.fields` |

`main` is **not** an ancestor of `stable` — they forked at `4955545`. A measurement taken on
`main` says nothing about `stable`; three wrong claims in one session came from forgetting
that. Verify every file, symbol and number against **this** checkout.

## Numbering

`v1` is the only tagged release (`v1-stable-2026-07-28`). Per `ver2-scope.md`, the build being
demoed on 28 Aug **is ver 2** — tag it `v2-stable-2026-08-28` on ship. Ver 3 is what follows.
Nothing is tagged at `01b30b9` yet.

## Running it

Two commands, in order, in one terminal. See `demo-2026-08-28.md` for the demo path.

```
cd "/Users/lap16603/Documents/New project/work/CTV_APReview-stable/server"
python3 -m uvicorn app:app --host 127.0.0.1 --port 8002
```

```
cd "/Users/lap16603/Documents/New project/work/CTV_APReview-stable"
node_modules/.bin/vite --host 127.0.0.1 --port 5175 --strictPort
```

Three constraints that will waste your time otherwise:

- **The UI is hardcoded to port 8002** (`src/upload/api.ts`) and CORS allows only 5173–5175.
- **Run ONE API server.** `CaseStore` caches its index in memory, so a second server on
  another port cannot see cases the first created. If a case is missing, restart the API.
- **Extraction is baked in at ingest; evaluation is computed per request.** A change to the
  evaluator or UI shows up immediately on existing cases. A change to OCR, anchors or bboxes
  needs a **re-ingest** (~20 min for 41 packets) to take effect.

To ingest with GreenNode IDP for the CCCD cards, export these before starting the API. Leave
`IDP_DOC_TYPE` **unset** — no working value is known and setting it fires doomed requests.

    GREENNODE_IDP_URL=https://<maas-host>/maas/<user-id>/greennode/idp/v1   # tenant-namespaced!
    GREENNODE_API_KEY=<key>

## Cases

| case | what it is |
|---|---|
| `68ddc1f0` `-idp-namefix` | newest: name fix + IDP cards (40/42 attached). **No** JPEG bbox fix |
| `87844b89` `-idp` | the frozen demo fallback, 39/42 cards |
| `fixed0boundaries0jul2026000000001` | pre-IDP baseline, useful for before/after |

`server/data/` is gitignored. Every case holds real PII — names, CCCD, bank accounts, scans.

## What landed today

Three behavioural fixes, each verified on real pages rather than fixtures:

- **`b7e2994`** `phi` gets a 3-line lookahead. Its anchor matches the section heading, not the
  clause. July 32/41 → 40/41 readable.
- **`afac45f`** name selection uses the two-column block's printed header instead of
  confidence. Cleared three false `no`s; batch diff 89/96 sources unchanged, 0 regressions.
- **`fccded7`** `_jpeg_size` returned JPEG header order (height first), transposing **every**
  CCCD card's page dimensions and so misplacing every card highlight.

Plus the ver 2 table list (`aab1d20`, `53823c7`, `d660a8a`) and the drawer stylesheet that had
never been ported from ver1 (`5bf33e6`).

## What to work on

Read `criteria-reliability.md` first — it says which of the 25 criteria actually decide
anything. Ranked by value:

1. **Packet 34's false `no`.** A confident double misread: CCCD `001100000151` for
   `001100000101` at 0.93 and 0.90, while MST on the same page reads correctly at 0.86.
   Confidence cannot catch it; a digit-level difference against an otherwise-consistent roster
   value is the signal to try. Last of the four false rejections still open.
2. **#15 PIT's threshold half.** It produces 14 of the batch's 20 `no` packets and 12 are
   genuine, but p27 and p31 are false — Gross 1,000,000 is below the withholding threshold, so
   PIT = 0 is lawful. The rule applies its commitment half but not its threshold half.
3. **`locate_field` should use `_is_labeled_anchor`.** Four of 48 hand-checked position markers
   land on prose (`validation-2026-08-27.md` §3). `find_name` already uses that guard.
4. **Document segmentation** before building #9–#13. Structurally sound (no page lost on 41 of
   41) but 16 packets carry a duplicated label — a BBNT split 1+2, or a 1-page contract whose
   body reads as `Tra cứu thuế`. Harmless today only because every Tier 1 field is on the
   contract's first page.
5. **`DATE` rejects a legible value.** `26/06/ 1984` fails `\d{1,2}/\d{1,2}/\d{4}` on the stray
   space. Audit the other patterns for the same.
6. **§2.1 IDP for document fields** — blocked on GreenNode naming a `doc_type`. Everything
   else is built and off behind `IDP_DOC_TYPE`.

## Things not to redo

- **Don't gate anything on `source.confidence`.** It is `min(word conf)` — legibility, not
  correctness. Wrong reads at 0.93, correct reads at 0.06.
- **Don't treat agreement across documents as corroboration.** The same misread repeats on two
  documents of similar scan quality.
- **`packet["pages"]` in `case.json` is `[first, last]`, a range** — not a list of pages.
- **A manifest page's `src` is an absolute path from ingest time** and may point nowhere. Only
  the `pgN.png` basename is durable; rebuild from the case directory.
- **`pending` outranks `ok`** in `criteria._SEVERITY`, so one unevaluated cell suppresses a
  criterion's pass. Judge the engine at cell level, not by rollup.

## Loose ends

- `machineRead` on `main`'s `feat/surface-autostatus-in-checklist` is uncommitted and stranded
  on a lineage that is not this one. Recommend dropping it.
- `CaseStore._write` has no temp+rename, lock or fsync; an interrupted write truncates the only
  copy of every reviewer decision, and `server/data` is gitignored.
- Reviewer decisions are keyed by packet **index**, which is unsafe across a re-ingest.
- A synthetic PII-free demo case was deleted and never rebuilt; there is no committed
  generator for one.
