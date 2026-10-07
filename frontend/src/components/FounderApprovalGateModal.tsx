import React, { useState } from 'react'
import type { CompanyRun, RepositoryProject } from '../types/company'

interface FounderApprovalGateModalProps {
  run: CompanyRun | null
  activeProject: RepositoryProject | null
  patchDiff?: string | null
  onClose: () => void
  onApprove: (runId: string) => Promise<any>
  onReject: (runId: string, reason: string) => Promise<any>
  onApply?: (runId: string) => Promise<any>
}

export const FounderApprovalGateModal: React.FC<FounderApprovalGateModalProps> = ({
  run,
  activeProject,
  patchDiff,
  onClose,
  onApprove,
  onReject,
  onApply,
}) => {
  const [rejecting, setRejecting] = useState<boolean>(false)
  const [rejectReason, setRejectReason] = useState<string>('')
  const [loading, setLoading] = useState<boolean>(false)
  const [actionError, setActionError] = useState<string | null>(null)

  if (!run) return null

  const proposal = run.proposal
  const grant = run.grant
  const receipt = run.receipt

  const isApproved = Boolean(grant || run.real_repo_apply_grant_id)
  const isApplied = Boolean(receipt || run.real_repo_apply_result)

  const handleApprove = async () => {
    try {
      setLoading(true)
      setActionError(null)
      await onApprove(run.run_id)
    } catch (err: any) {
      setActionError(err.message || 'Approval failed')
    } finally {
      setLoading(false)
    }
  }

  const handleReject = async () => {
    if (!rejectReason.trim()) {
      setActionError('Please specify a reason for rejection.')
      return
    }
    try {
      setLoading(true)
      setActionError(null)
      await onReject(run.run_id, rejectReason)
      setRejecting(false)
    } catch (err: any) {
      setActionError(err.message || 'Rejection failed')
    } finally {
      setLoading(false)
    }
  }

  const handleApply = async () => {
    if (!onApply) return
    try {
      setLoading(true)
      setActionError(null)
      await onApply(run.run_id)
    } catch (err: any) {
      setActionError(err.message || 'RealRepoApply execution failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="modal-backdrop" data-testid="founder-approval-modal">
      <div className="approval-modal-card">
        {/* Header */}
        <div className="approval-modal-header">
          <div className="header-badge-row">
            <span className="gate-tag">🛡️ FOUNDER GOVERNANCE GATE</span>
            <span className="qa-certified-badge">QA VERDICT: {run.qa_verdict || 'PASS'}</span>
          </div>
          <h2 className="approval-modal-title">Human Authorization: Real Repository Apply</h2>
          <p className="approval-modal-subtitle">
            An autonomous engineering proposal has passed QA verification and requires explicit
            Founder authorization before real repository changes can be applied.
          </p>
        </div>

        {/* Target Repository Guards & Pre-Apply State */}
        <div className="target-guard-summary-box">
          <h4 className="guard-section-title">TARGET REPOSITORY IDENTITY & GUARDS</h4>
          <div className="guard-grid">
            <div className="guard-item">
              <span className="guard-k">Project:</span>
              <span className="guard-v">{activeProject?.name || 'Jester'}</span>
            </div>
            <div className="guard-item">
              <span className="guard-k">Project ID:</span>
              <code>{run.project_id || 'prj_jester'}</code>
            </div>
            <div className="guard-item">
              <span className="guard-k">Repository Path:</span>
              <code className="path-code">
                {proposal?.target_repository_root ||
                  activeProject?.repository.root_path ||
                  'C:\\Users\\fiord\\OneDrive\\Desktop\\Jester'}
              </code>
            </div>
            <div className="guard-item">
              <span className="guard-k">Branch:</span>
              <span className="branch-pill">🌱 {proposal?.target_branch || 'main'}</span>
            </div>
            <div className="guard-item">
              <span className="guard-k">Base Commit:</span>
              <code>{proposal?.base_commit_hash?.substring(0, 12)}...</code>
            </div>
            <div className="guard-item">
              <span className="guard-k">Proposal ID:</span>
              <code>{proposal?.proposal_id || run.real_repo_apply_proposal_id || 'N/A'}</code>
            </div>
            <div className="guard-item">
              <span className="guard-k">Patch SHA-256:</span>
              <code className="hash-code">
                {proposal?.code_patch_sha256?.substring(0, 16)}...
              </code>
            </div>
            <div className="guard-item">
              <span className="guard-k">Changes Budget:</span>
              <span className="stat-pill">
                {proposal?.expected_changed_files?.length || 2} files authorized
              </span>
            </div>
          </div>
        </div>

        {/* Authorized Files List */}
        <div className="authorized-files-section">
          <span className="auth-title">Authorized File Mutations:</span>
          <div className="auth-files-list">
            {(proposal?.expected_changed_files || [
              'backend/app/core/canonical.py',
              'tests/core/test_canonical.py',
            ]).map((file) => (
              <div key={file} className="auth-file-item">
                <span className="file-dot">●</span>
                <code>{file}</code>
              </div>
            ))}
          </div>
        </div>

        {/* Diff Preview */}
        {patchDiff && (
          <div className="modal-diff-preview">
            <span className="diff-preview-title">Unified Diff Review:</span>
            <pre className="diff-pre-box">
              {patchDiff.slice(0, 1200)}
              {patchDiff.length > 1200 && '\n... [truncated for preview]'}
            </pre>
          </div>
        )}

        {/* Action Error Banner */}
        {actionError && (
          <div className="approval-error-banner" data-testid="approval-error">
            <span>⚠️ {actionError}</span>
          </div>
        )}

        {/* Rejection Input */}
        {rejecting ? (
          <div className="reject-reason-box">
            <label className="reason-label" htmlFor="reject-reason-input">
              Founder Reason for Rejection:
            </label>
            <textarea
              id="reject-reason-input"
              className="reject-textarea"
              placeholder="Explain why this proposal is rejected (e.g. scope too broad, interface mismatch)..."
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              rows={3}
            />
            <div className="reject-action-row">
              <button
                className="btn-danger-confirm"
                onClick={handleReject}
                disabled={loading}
                type="button"
                data-testid="confirm-reject-btn"
              >
                {loading ? 'Rejecting...' : 'Confirm Rejection'}
              </button>
              <button
                className="btn-secondary"
                onClick={() => setRejecting(false)}
                type="button"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          /* Modal Actions Footer */
          <div className="approval-modal-footer">
            <button className="btn-secondary" onClick={onClose} type="button">
              Close
            </button>

            {!isApproved && !isApplied && (
              <>
                <button
                  className="btn-danger-outline"
                  onClick={() => setRejecting(true)}
                  type="button"
                  data-testid="reject-proposal-btn"
                >
                  Reject Proposal
                </button>
                <button
                  className="btn-founder-primary"
                  onClick={handleApprove}
                  disabled={loading}
                  type="button"
                  data-testid="approve-proposal-btn"
                >
                  {loading ? 'Authorizing...' : '🛡️ Approve Proposal (Issue Grant)'}
                </button>
              </>
            )}

            {isApproved && !isApplied && (
              <button
                className="btn-execute-apply-primary"
                onClick={handleApply}
                disabled={loading}
                type="button"
                data-testid="execute-real-repo-apply-btn"
              >
                {loading ? 'Applying...' : '🚀 Execute RealRepoApply Transaction'}
              </button>
            )}

            {isApplied && (
              <span className="applied-success-badge">
                ✓ Applied via Human-Approved Transaction (Receipt Stored)
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
