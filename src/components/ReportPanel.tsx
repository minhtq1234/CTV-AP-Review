import { useEffect, useState } from 'react'
import { generateReport, reportUrls, type Report } from '../upload/api'

interface Props { caseId: string; onClose: () => void }

export default function ReportPanel({ caseId, onClose }: Props) {
  const [report, setReport] = useState<Report | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    generateReport(caseId).then(setReport).catch(() => setErr('Không tạo được báo cáo.'))
  }, [caseId])

  const urls = reportUrls(caseId)
  return (
    <div className="report-overlay" onClick={onClose}>
      <div className="report-panel" onClick={e => e.stopPropagation()}>
        <div className="report-head">
          <h3>Báo cáo cần gửi lại</h3>
          <button className="btn" onClick={onClose}>Đóng</button>
        </div>
        {err && <p className="upload-error">{err}</p>}
        {!report && !err && <p>Đang tạo…</p>}
        {report && (
          <>
            <div className="report-actions">
              <button className="btn" onClick={() => {
                navigator.clipboard.writeText(report.markdown)
                  .then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500) })
                  .catch(() => setErr('Không sao chép được — hãy chọn và copy thủ công.'))
              }}>{copied ? 'Đã sao chép' : 'Sao chép (Markdown)'}</button>
              <a className="btn" href={urls.md} download={`bao-cao-${caseId}.md`}>Tải .md</a>
              <a className="btn" href={urls.csv} download={`bao-cao-${caseId}.csv`}>Tải .csv</a>
            </div>
            {report.groups.length === 0
              ? <p className="report-empty">Không có mục nào cần gửi lại. 🎉</p>
              : <pre className="report-preview">{report.markdown}</pre>}
          </>
        )}
      </div>
    </div>
  )
}
