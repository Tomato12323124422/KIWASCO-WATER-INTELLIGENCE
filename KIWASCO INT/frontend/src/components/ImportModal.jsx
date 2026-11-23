import { useState, useRef } from 'react'
import { Upload, FileText, Download, X, AlertCircle, CheckCircle2 } from 'lucide-react'
import toast from 'react-hot-toast'

export default function ImportModal({
  isOpen,
  onClose,
  title = 'Import CSV',
  sampleHeaders = [],
  sampleRows = [],
  templateFileName = 'template.csv',
  onImport,
  onSuccess,
}) {
  const [file, setFile] = useState(null)
  const [preview, setPreview] = useState([])
  const [loading, setLoading] = useState(false)
  const [results, setResults] = useState(null)
  const fileInputRef = useRef(null)

  if (!isOpen) return null

  const handleDownloadTemplate = () => {
    const csvContent = [
      sampleHeaders.join(','),
      ...sampleRows.map(row => row.join(','))
    ].join('\n')

    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.setAttribute('download', templateFileName)
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
  }

  const handleFileChange = (e) => {
    const selected = e.target.files?.[0]
    if (!selected) return

    if (!selected.name.endsWith('.csv') && !selected.name.endsWith('.txt')) {
      toast.error('Please upload a valid .csv file')
      return
    }

    setFile(selected)
    setResults(null)

    const reader = new FileReader()
    reader.onload = (event) => {
      const text = event.target.result
      const lines = text.split(/\r?\n/).filter(line => line.trim().length > 0)
      if (lines.length > 0) {
        const rows = lines.slice(0, 6).map(line => line.split(',').map(c => c.trim()))
        setPreview(rows)
      }
    }
    reader.readAsText(selected)
  }

  const handleUpload = async () => {
    if (!file) return toast.error('Please choose a file to upload')
    setLoading(true)
    setResults(null)

    const formData = new FormData()
    formData.append('file', file)

    try {
      const res = await onImport(formData)
      setResults(res.data)
      if (res.data.success) {
        toast.success(`Successfully imported ${res.data.imported_count} records!`)
        if (onSuccess) onSuccess()
      }
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Import failed. Check CSV format.')
    } finally {
      setLoading(false)
    }
  }

  const resetState = () => {
    setFile(null)
    setPreview([])
    setResults(null)
    onClose()
  }

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 9999,
      background: 'rgba(7, 13, 31, 0.8)', backdropFilter: 'blur(8px)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20
    }}>
      <div className="card fade-up" style={{
        maxWidth: 620, width: '100%', maxHeight: '90vh', overflowY: 'auto',
        background: 'var(--bg-modal, #141e32)', border: '1px solid var(--border-subtle)',
        boxShadow: '0 24px 48px rgba(0,0,0,0.6)', padding: 24, position: 'relative'
      }}>
        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div style={{
              width: 38, height: 38, borderRadius: 10,
              background: 'rgba(14,165,233,0.15)', display: 'flex', alignItems: 'center', justifyContent: 'center',
              color: '#0ea5e9'
            }}>
              <Upload size={18} />
            </div>
            <div>
              <div style={{ fontSize: 16, fontWeight: 700 }}>{title}</div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Bulk ingest records via CSV file</div>
            </div>
          </div>
          <button onClick={resetState} style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', padding: 4 }}>
            <X size={20} />
          </button>
        </div>

        {/* Template Download Card */}
        <div style={{
          background: 'rgba(15, 26, 46, 0.7)', border: '1px dashed var(--border-subtle)',
          borderRadius: 8, padding: 14, marginBottom: 20, display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10
        }}>
          <div>
            <div style={{ fontSize: 13, fontWeight: 600 }}>Need the standard CSV format?</div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Columns: {sampleHeaders.join(', ')}</div>
          </div>
          <button className="btn btn-outline" onClick={handleDownloadTemplate} style={{ fontSize: 12, padding: '6px 12px' }}>
            <Download size={13} style={{ marginRight: 6 }} /> Download Template
          </button>
        </div>

        {/* File Chooser */}
        <div style={{
          border: '2px dashed var(--border-subtle)', borderRadius: 10, padding: 24,
          textAlign: 'center', cursor: 'pointer', background: 'rgba(15, 23, 42, 0.3)', marginBottom: 20,
          transition: 'border-color 0.2s ease'
        }}
        onClick={() => fileInputRef.current?.click()}
        >
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleFileChange}
            accept=".csv,.txt"
            style={{ display: 'none' }}
          />
          <FileText size={32} style={{ color: '#0ea5e9', margin: '0 auto 8px', display: 'block' }} />
          <div style={{ fontSize: 14, fontWeight: 600 }}>
            {file ? file.name : 'Click to select CSV file'}
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>
            {file ? `${(file.size / 1024).toFixed(1)} KB selected` : 'Supports UTF-8 CSV files'}
          </div>
        </div>

        {/* Live Preview Table */}
        {preview.length > 0 && (
          <div style={{ marginBottom: 20 }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 8 }}>
              File Preview (First {preview.length - 1} rows)
            </div>
            <div className="table-wrap" style={{ maxHeight: 180, overflowY: 'auto' }}>
              <table style={{ fontSize: 11 }}>
                <thead>
                  <tr>
                    {preview[0].map((h, i) => (
                      <th key={i} style={{ padding: '6px 10px', background: '#0f172a' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {preview.slice(1).map((row, idx) => (
                    <tr key={idx}>
                      {row.map((cell, cIdx) => (
                        <td key={cIdx} style={{ padding: '6px 10px' }}>{cell}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Results / Errors */}
        {results && (
          <div style={{
            padding: 12, borderRadius: 8, marginBottom: 16,
            background: results.success ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)',
            border: `1px solid ${results.success ? 'rgba(16, 185, 129, 0.3)' : 'rgba(239, 68, 68, 0.3)'}`
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, fontWeight: 600, color: results.success ? '#10b981' : '#ef4444' }}>
              {results.success ? <CheckCircle2 size={16} /> : <AlertCircle size={16} />}
              Imported {results.imported_count} records successfully!
            </div>
            {results.errors?.length > 0 && (
              <div style={{ marginTop: 8, fontSize: 11, color: '#f87171' }}>
                <div style={{ fontWeight: 600 }}>{results.total_errors} rows had issues:</div>
                <ul style={{ margin: '4px 0 0 16px', padding: 0 }}>
                  {results.errors.map((e, i) => <li key={i}>{e}</li>)}
                </ul>
              </div>
            )}
          </div>
        )}

        {/* Actions */}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
          <button className="btn btn-outline" onClick={resetState} disabled={loading}>
            Close
          </button>
          <button className="btn btn-primary" onClick={handleUpload} disabled={!file || loading}>
            {loading ? <><div className="spinner" /> Processing…</> : <><Upload size={14} style={{ marginRight: 6 }} /> Start Import</>}
          </button>
        </div>
      </div>
    </div>
  )
}
