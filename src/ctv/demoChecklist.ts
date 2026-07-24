import type { CtvFolder, EvidenceKind, CheckItem, CheckAutoStatus, CheckFocus, EvidenceDoc } from './types'

// Pure builder: maps a synthetic CtvFolder (src/ctv/folders.ts) to the same coded,
// two-tier checklist shape the backend produces (server/checklist.py's build_checklist),
// so the offline single-file demo renders through the same ChecklistPanel/FolderReview
// UI as the live reviewer. No IO here -- just folder.fields/docs -> CheckItem[].

const docByKind = (folder: CtvFolder, kind: EvidenceKind): string | null =>
  folder.docs.find(d => d.kind === kind)?.id ?? null

const DIACRITIC_SPECIAL: Record<string, string> = { đ: 'd', Đ: 'D' }

function norm(s: string): string {
  const swapped = (s || '').split('').map(ch => DIACRITIC_SPECIAL[ch] ?? ch).join('')
  return swapped.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().trim()
}

const digits = (s: string): string => (s || '').replace(/\D/g, '')

const SIGN_CAPTION = 'Khu vực chữ ký & con dấu'
const SIGN_BAND_FRAC = 0.28

function signatureFocus(doc: EvidenceDoc | undefined): CheckFocus | null {
  if (!doc || doc.pages.length === 0) return null
  const last = doc.pages.length - 1
  const { width: w, height: h } = doc.pages[last]
  if (!w || !h) return null
  const band = Math.round(h * SIGN_BAND_FRAC)
  return { page: last, caption: SIGN_CAPTION, bbox: { x: 0, y: h - band, width: w, height: band } }
}

const bbntForC2 = (folder: CtvFolder): EvidenceDoc | undefined => {
  const bbnts = folder.docs.filter(d => d.kind === 'bbnt')
  return bbnts.find(d => norm(d.label).includes('thanh ly')) ?? bbnts[0]
}

// Mirrors checklist.py's _autostatus: digits-only fields (CCCD, phone, amounts) compare on
// digits alone so currency/format noise ("10.000.000" vs "10.000.000 ₫") doesn't false-mismatch;
// everything else compares diacritic/case-normalized. No readable source at all -> 'review'.
function autostatus(reference: string, source: { value: string } | null): CheckAutoStatus {
  const value = source?.value ?? ''
  if (!source || !value) return 'review'
  if (digits(reference) && digits(value)) return digits(reference) === digits(value) ? 'match' : 'mismatch'
  return norm(reference) === norm(value) ? 'match' : 'mismatch'
}

// [code, label, folder field key, routed doc kind] -- mirrors server/checklist.py's _VALUE
// table, minus the rows the synthetic folders have no field for (`mst` -> A2; see
// folders.ts's field keys). The routed kind is what a document-routed value check (e.g. B1's
// "họ tên") prefers a source from -- so, say, a typed BBNT source never outranks the
// contract's own (possibly unread) slot just by being sources[0].
const VALUE: ReadonlyArray<readonly [string, string, string, EvidenceKind]> = [
  ['B1', 'Họ tên khớp bảng kê', 'name', 'contract'],
  ['A1', 'Số CCCD khớp giữa chứng từ', 'cccd', 'contract'],
  ['B2', 'Phí dịch vụ khớp bảng kê', 'gross', 'contract'],
  ['BANK', 'Số tài khoản khớp bảng kê', 'bank_acct', 'contract'],
  ['INFO', 'Ngày sinh khớp hồ sơ', 'dob', 'contract'],
]

export function demoChecklist(folder: CtvFolder): CheckItem[] {
  const byKey = new Map(folder.fields.map(f => [f.key, f] as const))
  const contract = docByKind(folder, 'contract') ?? folder.docs[0]?.id ?? null
  const commitment = docByKind(folder, 'commitment')
  const bbnt = docByKind(folder, 'bbnt')

  const checks: CheckItem[] = [
    { code: 'G-DOC', label: 'Đủ chứng từ bắt buộc', tier: 'gate', kind: 'confirm',
      evidenceDocId: null, reference: null, source: null, autostatus: null },
  ]
  if (commitment) checks.push(
    { code: 'D3', label: 'Cam kết TNCN đúng mẫu năm hiện hành', tier: 'gate', kind: 'confirm',
      evidenceDocId: commitment, reference: null, source: null, autostatus: null })
  checks.push(
    { code: 'B3', label: 'Hợp đồng đủ chữ ký & con dấu', tier: 'gate', kind: 'confirm',
      evidenceDocId: contract, reference: null, source: null, autostatus: null,
      focus: signatureFocus(folder.docs.find(d => d.kind === 'contract')) })
  const c2doc = bbntForC2(folder)
  if (c2doc) checks.push(
    { code: 'C2', label: 'BBNT đủ chữ ký, con dấu & giáp lai', tier: 'gate', kind: 'confirm',
      evidenceDocId: c2doc.id, reference: null, source: null, autostatus: null,
      focus: signatureFocus(c2doc) })

  for (const [code, label, fieldKey, routedKind] of VALUE) {
    const f = byKey.get(fieldKey)
    if (!f) continue
    const routed = docByKind(folder, routedKind) ?? contract
    const src = f.sources.find(s => s.docId === routed) ?? f.sources[0] ?? null
    checks.push({
      code, label, tier: 'detail', kind: 'value',
      evidenceDocId: src?.docId ?? routed,
      reference: f.expected ?? '', source: src,
      autostatus: autostatus(f.expected ?? '', src),
    })
  }

  if (bbnt) checks.push(
    { code: 'C1', label: 'Nội dung & thời gian khớp BBNT', tier: 'detail', kind: 'confirm',
      evidenceDocId: bbnt, reference: null, source: null, autostatus: null })
  if (commitment) checks.push(
    { code: 'D1', label: 'Thông tin & MST khớp cam kết', tier: 'detail', kind: 'confirm',
      evidenceDocId: commitment, reference: null, source: null, autostatus: null })

  return checks
}
