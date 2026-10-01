import React, { useState, useRef, useEffect } from 'react'
import type { ChatMessage } from '../types/company'

interface CompanyChatProps {
  isOpen: boolean
  onClose: () => void
  onToggle: () => void
  messages: ChatMessage[]
  onSendMessage: (content: string) => Promise<any>
}

const DEFAULT_SUGGESTIONS = [
  'What is our company status?',
  'I need a website for my restaurant.',
  'Review the active deliverable.',
  'Run independent QA verification.',
]

export const CompanyChat: React.FC<CompanyChatProps> = ({
  isOpen,
  onClose,
  onToggle,
  messages,
  onSendMessage,
}) => {
  const [inputVal, setInputVal] = useState('')
  const [sending, setSending] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement | null>(null)

  const scrollToBottom = () => {
    if (typeof messagesEndRef.current?.scrollIntoView === 'function') {
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }

  useEffect(() => {
    if (isOpen) {
      scrollToBottom()
    }
  }, [messages, isOpen])

  const handleSend = async (contentToSend?: string) => {
    const text = (contentToSend ?? inputVal).trim()
    if (!text || sending) return

    setSending(true)
    setInputVal('')
    try {
      await onSendMessage(text)
    } finally {
      setSending(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <>
      {/* Floating launcher when closed */}
      {!isOpen && (
        <button
          className="chat-launcher-btn"
          onClick={onToggle}
          title="Open Company Chat"
          data-testid="chat-launcher-btn"
        >
          <span>💬</span>
          <span>Company Chat</span>
          <span className="chat-count-badge" data-testid="chat-count-badge">
            {messages.length}
          </span>
        </button>
      )}

      {/* Drawer when open */}
      {isOpen && (
        <aside className="chat-drawer" data-testid="company-chat-drawer">
          <div className="chat-header">
            <div className="chat-header-title">
              <span>💬</span>
              <span>Company Chat</span>
              <span style={{ fontSize: '12px', color: 'var(--text-muted)', fontWeight: 500 }}>
                · Direct Channel
              </span>
            </div>
            <button
              className="chat-close-btn"
              onClick={onClose}
              title="Close chat"
              data-testid="chat-close-btn"
            >
              ✕
            </button>
          </div>

          <div className="chat-messages-stream" data-testid="chat-message-stream">
            {messages.length === 0 ? (
              <div style={{ color: 'var(--text-muted)', fontSize: '13px', textAlign: 'center', marginTop: '20px' }}>
                Connecting to CEO and workforce...
              </div>
            ) : (
              messages.map((msg) => {
                const isOwner = msg.sender_role.toLowerCase() === 'owner'
                return (
                  <div
                    key={msg.id}
                    className={`chat-bubble ${isOwner ? 'owner' : 'ceo'}`}
                    data-testid={`chat-bubble-${msg.id}`}
                  >
                    <div className="chat-sender-label">
                      {isOwner ? 'You (Founder)' : msg.sender_name || 'CEO Agent'}
                    </div>
                    <div style={{ whiteSpace: 'pre-line' }}>{msg.content}</div>
                  </div>
                )
              })
            )}
            <div ref={messagesEndRef} />
          </div>

          <div className="chat-suggestions">
            {DEFAULT_SUGGESTIONS.map((sug, idx) => (
              <button
                key={idx}
                className="suggestion-chip"
                onClick={() => handleSend(sug)}
                disabled={sending}
                data-testid={`suggestion-chip-${idx}`}
              >
                {sug}
              </button>
            ))}
          </div>

          <div className="chat-input-bar">
            <input
              type="text"
              className="chat-input-field"
              placeholder="Direct your company or ask the CEO..."
              value={inputVal}
              onChange={(e) => setInputVal(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={sending}
              data-testid="chat-input-field"
            />
            <button
              className="chat-send-btn"
              onClick={() => handleSend()}
              disabled={sending || !inputVal.trim()}
              data-testid="chat-send-btn"
            >
              {sending ? '...' : 'Send ➔'}
            </button>
          </div>
        </aside>
      )}
    </>
  )
}
