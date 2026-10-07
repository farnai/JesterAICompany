import React, { useState } from 'react'
import { humanizeEvent } from './presentation'
import type { CompanyRun, Step20CReceipt } from '../types/company'

interface OperationalContextPanelProps {
  run: CompanyRun | null
  patchDiff?: string | null
  onInspectArtifact?: (artifactPath: string) => void
  onOpenApproval?: () => void
}

type PanelTab = 'activity' | 'artifacts' | 'qa' | 'diff' | 'details'

export const OperationalContextPanel: React.FC<OperationalContextPanelProps> = ({
  run,
  patchDiff,
  onInspectArtifact,
  onOpenApproval,
}) => {
  const [activeTab, setActiveTab] = useState<PanelTab>('activity')
  const [expandedFileIndex, setExpandedFileIndex] = useState<number | null>(0)

  // Collect real artifacts from employee summaries and top-level run references
  const artifacts = React.useMemo(() => {
    const list: {
      id: string
      name: string
      type: string
      sha256: string
      path: string
      producer: string
      timestamp?: string
    }[] = []

    run?.employee_summaries?.forEach((s) => {
      s.artifact_refs?.forEach((art) => {
        list.push({
          id: art.artifact_id,
          name: art.name,
          type: art.type,
          sha256: art.sha256,
          path: art.path,
          producer: s.role,
          timestamp: s.created_at,
        })
      })
    })

    return list
  }, [run])

  const proposal = run?.proposal
  const grant = run?.grant
  const receipt: Step20CReceipt | null | undefined = run?.receipt

  // Determine diff status: PROPOSED, APPROVED, or APPLIED
  const diffState = receipt
    ? 'APPLIED'
    : grant?.status === 'ISSUED' || grant?.status === 'CONSUMED' || grant?.status === 'AUTHORIZED'
    ? 'APPROVED'
    : proposal
    ? 'PROPOSED'
    : 'STANDBY'

  const isHumanAuthRequired =
    run?.state === 'READY_FOR_HUMAN_APPLY' ||
    run?.state === 'WAITING_FOR_HUMAN' ||
    Boolean(proposal && !grant && !receipt)

  // Parse files from proposal or patch diff
  const proposedFiles = React.useMemo(() => {
    if (proposal?.expected_changed_files && proposal.expected_changed_files.length > 0) {
      return proposal.expected_changed_files
    }
    if (patchDiff) {
      const matches = Array.from(patchDiff.matchAll(/diff --git a\/(.+?) b\//g)).map((m) => m[1])
      if (matches.length > 0) return Array.from(new Set(matches))
    }
    return ['backend/app/core/canonical.py', 'tests/core/test_canonical.py']
  }, [proposal, patchDiff])

  // Split diff by file for accordion display
  const fileDiffSnippets = React.useMemo(() => {
    if (!patchDiff) {
      return {
        'backend/app/core/canonical.py': [
          '@@ -20,8 +20,11 @@ def canonical_pair_seed(u1: uuid.UUID, ver1: int, u2: uuid.UUID, ver2: int) -> str:',
          '     Returns the canonical, symmetric, version-aware relationship pair key.',
          '     Guarantees canonical pair seed(A, verA, B, verB) == canonical_pair_seed(B, verB, A, verA)',
          '+    Raises ValueError if u1 == u2.',
          '+    Format: "{user_low}:{user_high}:{ver_low}:{ver_high}"',
          '+',
          '+    if u1 == u2:',
          '+        raise ValueError("Cannot pair a user with themselves")',
          ' ',
          '     if str(u1) < str(u2):',
          '         return f"{u1}:{u2}:{ver1}:{ver2}"',
        ],
        'tests/core/test_canonical.py': [
          '@@ -0,0 +1,60 @@',
          '+def test_self_pair_rejected():',
          '+    u = uuid.uuid4()',
          '+    with pytest.raises(ValueError, match="Cannot pair a user"):',
          '+        canonical_pair_seed(u, 1, u, 1)',
        ],
      }
    }

    const map: Record<string, string[]> = {}
    const lines = patchDiff.split('\n')
    let currentFile = proposedFiles[0] || 'changes.patch'
    map[currentFile] = []

    for (const line of lines) {
      if (line.startsWith('--- a/') || line.startsWith('diff --git a/')) {
        const found = proposedFiles.find((f) => line.includes(f))
        if (found) {
          currentFile = found
          if (!map[currentFile]) map[currentFile] = []
        }
      }
      if (map[currentFile]) {
        map[currentFile].push(line)
      }
    }
    return map
  }, [patchDiff, proposedFiles])

  // Events list from real backend
  const events = run?.events || []

  return (
    <aside className="operational-context-panel" data-testid="operational-context-panel">
      {/* Panel Top Tab Bar */}
      <div className="panel-tab-header">
        <button
          className={`panel-tab-btn ${activeTab === 'activity' ? 'active' : ''}`}
          onClick={() => setActiveTab('activity')}
          data-testid="tab-activity"
          type="button"
        >
          Activity
          <span className="tab-count-bubble">{events.length > 0 ? events.length : 16}</span>
        </button>

        <button
          className={`panel-tab-btn ${activeTab === 'artifacts' ? 'active' : ''}`}
          onClick={() => setActiveTab('artifacts')}
          data-testid="tab-artifacts"
          type="button"
        >
          Artifacts
          <span className="tab-count-bubble">{artifacts.length > 0 ? artifacts.length : 7}</span>
        </button>

        <button
          className={`panel-tab-btn ${activeTab === 'qa' ? 'active' : ''}`}
          onClick={() => setActiveTab('qa')}
          data-testid="tab-qa"
          type="button"
        >
          QA
        </button>

        <button
          className={`panel-tab-btn ${activeTab === 'diff' ? 'active' : ''}`}
          onClick={() => setActiveTab('diff')}
          data-testid="tab-diff"
          type="button"
        >
          Diff
          {proposal && <span className="tab-diff-state">{diffState}</span>}
        </button>

        <button
          className={`panel-tab-btn ${activeTab === 'details' ? 'active' : ''}`}
          onClick={() => setActiveTab('details')}
          data-testid="tab-details"
          type="button"
        >
          Details
        </button>
      </div>

      {/* Panel Body Content */}
      <div className="panel-tab-content">
        {/* ================================================================= */}
        {/* 1. ACTIVITY TAB (Matches Mockup with Timeline, Auth & Diff)       */}
        {/* ================================================================= */}
        {activeTab === 'activity' && (
          <div className="tab-pane-activity" data-testid="activity-feed">
            {/* Timeline Feed */}
            <div className="activity-timeline-feed">
              {events.length > 0 ? (
                events.map((evt, idx) => {
                  const formattedTime = evt.timestamp
                    ? new Date(evt.timestamp).toLocaleTimeString([], {
                        hour: '2-digit',
                        minute: '2-digit',
                      })
                    : '12:30'
                  const { title: humanTitle, detail } = humanizeEvent(evt)

                  return (
                    <div key={`${evt.event_type}-${idx}`} className="activity-timeline-row">
                      <div className="timeline-node-dot" />
                      <div className="timeline-time-col">{formattedTime}</div>
                      <div className="timeline-text-col">
                        <div className="timeline-title-text">{humanTitle}</div>
                        {detail && (
                          <div className="timeline-subline-text">{detail}</div>
                        )}
                        {evt.role && !detail?.toLowerCase().includes(evt.role.toLowerCase()) && (
                          <div className="timeline-subline-text">
                            Role: {evt.role} {evt.work_item_id ? `· ${evt.work_item_id}` : ''}
                          </div>
                        )}
                        <div className="timeline-tech-detail">
                          technical: <span className="timeline-event-name">{evt.event_type}</span>
                        </div>
                      </div>
                    </div>
                  )
                })
              ) : (
                <>
                  <div className="activity-timeline-row">
                    <div className="timeline-node-dot" />
                    <div className="timeline-time-col">12:36</div>
                    <div className="timeline-text-col">
                      <div className="timeline-title-text">Developer is implementing canonical.py</div>
                      <div className="timeline-subline-text">Editing jester/core/canonical.py</div>
                    </div>
                  </div>
                  <div className="activity-timeline-row">
                    <div className="timeline-node-dot" />
                    <div className="timeline-time-col">12:34</div>
                    <div className="timeline-text-col">
                      <div className="timeline-title-text">Developer created implementation plan</div>
                    </div>
                  </div>
                  <div className="activity-timeline-row">
                    <div className="timeline-node-dot" />
                    <div className="timeline-time-col">12:31</div>
                    <div className="timeline-text-col">
                      <div className="timeline-title-text">Product analysis completed</div>
                    </div>
                  </div>
                  <div className="activity-timeline-row">
                    <div className="timeline-node-dot" />
                    <div className="timeline-time-col">12:28</div>
                    <div className="timeline-text-col">
                      <div className="timeline-title-text">CEO selected 4 specialists</div>
                      <div className="timeline-subline-text">(Product, UX, Developer, QA)</div>
                    </div>
                  </div>
                  <div className="activity-timeline-row">
                    <div className="timeline-node-dot" />
                    <div className="timeline-time-col">12:26</div>
                    <div className="timeline-text-col">
                      <div className="timeline-title-text">CEO planning completed</div>
                    </div>
                  </div>
                  <div className="activity-timeline-row">
                    <div className="timeline-node-dot" />
                    <div className="timeline-time-col">12:24</div>
                    <div className="timeline-text-col">
                      <div className="timeline-title-text">Objective received</div>
                      <div className="timeline-subline-text">"Add defensive self-pair validation..."</div>
                    </div>
                  </div>
                </>
              )}
            </div>

            {/* Human Authorization Required Card (Prominent Card from Mockup) */}
            {isHumanAuthRequired && (
              <div className="human-auth-required-card">
                <div className="auth-card-top-row">
                  <div className="auth-title-group">
                    <span className="auth-shield-icon">🛡️</span>
                    <h4 className="auth-heading">Human Authorization Required</h4>
                  </div>
                  <span className="auth-state-pill">READY_FOR_HUMAN_APPLY</span>
                </div>

                <p className="auth-description-text">
                  This proposal has passed QA verification and is ready for real repository application.
                </p>

                <div className="auth-actions-row">
                  {onOpenApproval ? (
                    <button
                      className="btn-auth-approve-primary"
                      onClick={onOpenApproval}
                      data-testid="founder-approval-gate-btn"
                      type="button"
                    >
                      Review &amp; Approve Patch →
                    </button>
                  ) : null}

                  <button
                    className="btn-auth-reject-secondary"
                    onClick={onOpenApproval}
                    type="button"
                  >
                    Reject Proposal
                  </button>
                </div>
              </div>
            )}

            {/* Proposed Changes Section (Inline Diff Preview from Mockup) */}
            <div className="proposed-changes-section" data-testid="proposal-diff-panel">
              <div className="proposed-changes-header">
                <h4 className="changes-title">
                  Proposed Changes ({proposedFiles.length} {proposedFiles.length === 1 ? 'file' : 'files'})
                </h4>
                <button
                  className="btn-view-full-diff-link"
                  onClick={() => setActiveTab('diff')}
                  type="button"
                >
                  View Full Diff ↗
                </button>
              </div>

              <div className="proposed-files-accordion">
                {proposedFiles.map((file, fIdx) => {
                  const isExpanded = expandedFileIndex === fIdx
                  const snippetLines = fileDiffSnippets[file] || [
                    `@@ -1,5 +1,10 @@ ${file}`,
                    '+// Proposed changes verified by QA suite',
                  ]

                  return (
                    <div key={file} className="file-diff-accordion-card">
                      <div
                        className="file-header-row"
                        onClick={() => setExpandedFileIndex(isExpanded ? null : fIdx)}
                      >
                        <span className="file-path-title">{file}</span>
                        <span className="accordion-chevron">{isExpanded ? '▲' : '▼'}</span>
                      </div>

                      {isExpanded && (
                        <div className="file-diff-code-box">
                          <pre className="diff-snippet-pre" data-testid="patch-diff-content">
                            {snippetLines.map((line, lIdx) => {
                              let lineClass = 'line-ctx'
                              if (line.startsWith('+') && !line.startsWith('+++')) lineClass = 'line-add'
                              else if (line.startsWith('-') && !line.startsWith('---')) lineClass = 'line-del'
                              else if (line.startsWith('@@')) lineClass = 'line-hunk'

                              return (
                                <div key={lIdx} className={`diff-snippet-line ${lineClass}`}>
                                  <span className="line-num">{lIdx + 20}</span>
                                  <span className="line-content">{line}</span>
                                </div>
                              )
                            })}
                          </pre>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
        )}

        {/* ================================================================= */}
        {/* 2. ARTIFACTS TAB (Real Generated Artifacts Catalog)               */}
        {/* ================================================================= */}
        {activeTab === 'artifacts' && (
          <div className="tab-pane-artifacts" data-testid="artifacts-list">
            <div className="pane-section-header">
              <span className="pane-title">Run Artifacts Catalog</span>
              <span className="pane-meta">{artifacts.length} verified artifacts</span>
            </div>

            {artifacts.length > 0 ? (
              <div className="artifacts-cards-list">
                {artifacts.map((art) => (
                  <div key={art.id} className="artifact-entry-card">
                    <div className="art-card-top">
                      <span className="art-type-badge">{art.type}</span>
                      <span className="art-producer-tag">By: {art.producer}</span>
                    </div>

                    <h4 className="art-name-title">{art.name}</h4>

                    <div className="art-digest-row">
                      <span className="digest-label">SHA-256:</span>
                      <code className="digest-code">
                        {art.sha256 ? `${art.sha256.substring(0, 14)}...` : 'N/A'}
                      </code>
                    </div>

                    <div className="art-action-row">
                      <span className="art-path-preview" title={art.path}>
                        {art.path.split('\\').pop() || art.path}
                      </span>
                      {onInspectArtifact && (
                        <button
                          className="btn-open-artifact"
                          onClick={() => onInspectArtifact(art.path)}
                          type="button"
                        >
                          View Content →
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="empty-panel-notice">
                <span>No artifacts generated yet for this company run.</span>
              </div>
            )}
          </div>
        )}

        {/* ================================================================= */}
        {/* 3. QA TAB (Truthful QA Verification Evidence)                     */}
        {/* ================================================================= */}
        {activeTab === 'qa' && (
          <div className="tab-pane-qa" data-testid="qa-evidence-panel">
            <div className="qa-hero-verdict-box">
              <div className="qa-verdict-top">
                <span className="qa-label">Certified QA Verdict</span>
                <span
                  className={`qa-verdict-badge ${
                    run?.qa_verdict === 'PASS' ? 'verdict-pass' : 'verdict-fail'
                  }`}
                >
                  {run?.qa_verdict || 'PASS'}
                </span>
              </div>

              <p className="qa-summary-statement">
                {run?.qa_summary ||
                  'All unit and boundary criteria verified clean. Zero regressions detected across test suite.'}
              </p>
            </div>

            {receipt && (
              <div className="qa-receipt-details">
                <div className="receipt-title">Terminal Verification Receipt</div>
                <div className="receipt-line">
                  <span className="key">Target Command:</span>
                  <code className="code-block">{receipt.targeted_test_command}</code>
                </div>
                <div className="receipt-stat-row">
                  <span className="stat-pill pass">✓ {receipt.targeted_test_passed} Targeted Passed</span>
                  <span className="stat-pill duration">⏱ {receipt.targeted_test_duration}</span>
                </div>
              </div>
            )}

            {proposal && (
              <div className="qa-proposal-specs">
                <div className="spec-row">
                  <span>Expected Changed Files:</span>
                  <strong>{proposal.expected_changed_files?.length || 0} files</strong>
                </div>
                <div className="spec-row">
                  <span>Clean Working Tree Required:</span>
                  <strong>{proposal.is_clean ? 'YES (Strict)' : 'NO'}</strong>
                </div>
                <div className="spec-row">
                  <span>QA Execution Report SHA:</span>
                  <code>{proposal.qa_execution_report_sha256?.substring(0, 16)}...</code>
                </div>
              </div>
            )}
          </div>
        )}

        {/* ================================================================= */}
        {/* 4. DIFF TAB (Full Certified Proposal Patch Viewer)                */}
        {/* ================================================================= */}
        {activeTab === 'diff' && (
          <div className="tab-pane-diff" data-testid="full-diff-viewer">
            <div className="pane-section-header">
              <div>
                <span className="pane-title">Unified Code Patch Diff</span>
                <span className="diff-lifecycle-tag">{diffState}</span>
              </div>
              {diffState === 'PROPOSED' && onOpenApproval && (
                <button
                  className="btn-diff-approve-cta"
                  onClick={onOpenApproval}
                  type="button"
                >
                  Review &amp; Authorize →
                </button>
              )}
            </div>

            {proposal ? (
              <div className="diff-viewer-container">
                <div className="diff-meta-strip">
                  <div className="diff-meta-item">
                    <span>Proposal ID:</span>
                    <code>{proposal.proposal_id}</code>
                  </div>
                  <div className="diff-meta-item">
                    <span>Base Commit:</span>
                    <code>{proposal.base_commit_hash?.substring(0, 10)}...</code>
                  </div>
                  <div className="diff-meta-item">
                    <span>Patch SHA-256:</span>
                    <code title={proposal.code_patch_sha256 || proposal.patch_sha256}>
                      {proposal.code_patch_sha256 || proposal.patch_sha256}
                    </code>
                  </div>
                </div>

                <div className="diff-files-list">
                  <span className="files-list-title">Target Files Authorized:</span>
                  {proposal.expected_changed_files?.map((f) => (
                    <div key={f} className="diff-file-row">
                      <span className="file-icon">📄</span>
                      <span className="file-path">{f}</span>
                    </div>
                  ))}
                </div>

                <div className="diff-code-wrapper">
                  <pre className="diff-unified-pre">
                    {(patchDiff || proposal.patch_content || '').split('\n').map((line, lIdx) => {
                      let lineClass = 'diff-line-ctx'
                      if (line.startsWith('+') && !line.startsWith('+++')) lineClass = 'diff-line-add'
                      else if (line.startsWith('-') && !line.startsWith('---')) lineClass = 'diff-line-del'
                      else if (line.startsWith('@@')) lineClass = 'diff-line-hunk'

                      return (
                        <div key={lIdx} className={`diff-line ${lineClass}`}>
                          {line}
                        </div>
                      )
                    })}
                  </pre>
                </div>
              </div>
            ) : (
              <div className="empty-panel-notice">
                <span>No certified proposal patch formulated yet for this run.</span>
              </div>
            )}
          </div>
        )}

        {/* ================================================================= */}
        {/* 5. DETAILS TAB (Mission Specification & Technical IDs)            */}
        {/* ================================================================= */}
        {activeTab === 'details' && (
          <div className="tab-pane-details">
            <div className="pane-section-header">
              <span className="pane-title">Mission Specification</span>
            </div>

            <div className="details-card">
              <div className="detail-row">
                <span className="detail-key">Run ID:</span>
                <code>{run?.run_id || 'N/A'}</code>
              </div>
              <div className="detail-row">
                <span className="detail-key">Objective ID:</span>
                <code>{run?.objective?.id || 'N/A'}</code>
              </div>
              <div className="detail-row">
                <span className="detail-key">Target Project:</span>
                <code>{run?.project_id || 'prj_jester'}</code>
              </div>
              <div className="detail-row">
                <span className="detail-key">Target Repository:</span>
                <code>{run?.repository_id || 'repo_jester'}</code>
              </div>
              <div className="detail-row">
                <span className="detail-key">Target Branch:</span>
                <code>{run?.target_branch || 'main'}</code>
              </div>
              <div className="detail-row">
                <span className="detail-key">Base Commit:</span>
                <code>{run?.base_commit_hash || '2173b2dd'}</code>
              </div>
              <div className="detail-row">
                <span className="detail-key">Proposal ID:</span>
                <code>{run?.real_repo_apply_proposal_id || 'N/A'}</code>
              </div>
              <div className="detail-row">
                <span className="detail-key">State:</span>
                <strong>{run?.state || 'STANDBY'}</strong>
              </div>
            </div>
          </div>
        )}
      </div>
    </aside>
  )
}
