import React, { useEffect, useState } from 'react'
import { api } from '../api/client'

interface ArtifactViewModalProps {
  artifactPath: string | null
  runId?: string
  onClose: () => void
}

export const ArtifactViewModal: React.FC<ArtifactViewModalProps> = ({
  artifactPath,
  runId,
  onClose,
}) => {
  const [content, setContent] = useState<string>('')
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState<boolean>(false)

  useEffect(() => {
    if (!artifactPath) return

    setLoading(true)
    setError(null)
    api
      .getArtifactContent(artifactPath, runId)
      .then((data) => {
        setContent(data || '')
      })
      .catch((err) => {
        setError(err?.message || 'Failed to fetch artifact content')
      })
      .finally(() => {
        setLoading(false)
      })
  }, [artifactPath, runId])

  if (!artifactPath) return null

  const fileName = artifactPath.split(/[\\/]/).pop() || artifactPath

  const handleCopy = () => {
    navigator.clipboard.writeText(content)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="modal-backdrop" data-testid="artifact-view-modal">
      <div className="artifact-modal-card">
        <div className="artifact-modal-header">
          <div>
            <span className="art-modal-tag">ARTIFACT INSPECTOR</span>
            <h3 className="art-modal-filename">{fileName}</h3>
            <code className="art-modal-path">{artifactPath}</code>
          </div>
          <div className="art-modal-actions">
            <button className="btn-secondary" onClick={handleCopy} type="button">
              {copied ? 'Copied ✓' : 'Copy'}
            </button>
            <button className="btn-secondary" onClick={onClose} type="button">
              Close
            </button>
          </div>
        </div>

        <div className="artifact-modal-body">
          {loading && <div className="art-loading">Loading verified artifact payload...</div>}
          {error && <div className="art-error">{error}</div>}
          {!loading && !error && (
            <pre className="art-content-pre">
              <code>{content}</code>
            </pre>
          )}
        </div>
      </div>
    </div>
  )
}
