import React, { useEffect, useState, useCallback } from 'react'

interface ConnectionDef {
  fromId: string
  toId: string
  isActive?: boolean
  isCompleted?: boolean
  label?: string
}

interface WorkforceConnectionOverlayProps {
  containerRef: React.RefObject<HTMLDivElement | null>
  connections: ConnectionDef[]
}

interface MeasuredPath {
  id: string
  d: string
  isActive: boolean
  isCompleted: boolean
  midX: number
  midY: number
}

export const WorkforceConnectionOverlay: React.FC<WorkforceConnectionOverlayProps> = ({
  containerRef,
  connections,
}) => {
  const [paths, setPaths] = useState<MeasuredPath[]>([])

  const measureConnections = useCallback(() => {
    if (!containerRef.current) return
    const containerRect = containerRef.current.getBoundingClientRect()

    const newPaths: MeasuredPath[] = []

    connections.forEach((conn, index) => {
      const fromEl = containerRef.current?.querySelector(`[data-anchor="${conn.fromId}"]`)
      const toEl = containerRef.current?.querySelector(`[data-anchor="${conn.toId}"]`)

      if (!fromEl || !toEl) return

      const fromRect = fromEl.getBoundingClientRect()
      const toRect = toEl.getBoundingClientRect()

      // Calculate relative coordinates to container
      const startX = fromRect.left + fromRect.width / 2 - containerRect.left
      const startY = fromRect.bottom - containerRect.top

      const endX = toRect.left + toRect.width / 2 - containerRect.left
      const endY = toRect.top - containerRect.top

      // Smooth vertical cubic bezier curve
      const dy = endY - startY
      const deltaY = Math.max(Math.abs(dy) * 0.5, 30)
      const cp1Y = startY + deltaY
      const cp2Y = endY - deltaY

      const d = `M ${startX} ${startY} C ${startX} ${cp1Y}, ${endX} ${cp2Y}, ${endX} ${endY}`

      newPaths.push({
        id: `${conn.fromId}->${conn.toId}-${index}`,
        d,
        isActive: Boolean(conn.isActive),
        isCompleted: Boolean(conn.isCompleted),
        midX: (startX + endX) / 2,
        midY: (startY + endY) / 2,
      })
    })

    setPaths(newPaths)
  }, [containerRef, connections])

  useEffect(() => {
    measureConnections()

    const container = containerRef.current
    if (!container) return

    const resizeObserver = new ResizeObserver(() => {
      measureConnections()
    })
    resizeObserver.observe(container)

    window.addEventListener('resize', measureConnections)

    // Periodic measure for animated layouts
    const interval = setInterval(measureConnections, 1000)

    return () => {
      resizeObserver.disconnect()
      window.removeEventListener('resize', measureConnections)
      clearInterval(interval)
    }
  }, [measureConnections, containerRef])

  return (
    <svg
      className="workforce-connector-svg"
      style={{
        position: 'absolute',
        top: 0,
        left: 0,
        width: '100%',
        height: '100%',
        pointerEvents: 'none',
        zIndex: 1,
        overflow: 'visible',
      }}
      aria-hidden="true"
    >
      <defs>
        {/* Subtle orange glow/filter for active connector */}
        <linearGradient id="activeConnectorGrad" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor="#F95924" stopOpacity="0.8" />
          <stop offset="100%" stopColor="#F95924" stopOpacity="1" />
        </linearGradient>
      </defs>

      {paths.map((p) => {
        const strokeColor = p.isActive
          ? '#F95924'
          : p.isCompleted
          ? '#FB923C'
          : '#E5E3DC'
        const strokeWidth = p.isActive ? 2.5 : 1.8
        const strokeDash = p.isActive ? 'none' : p.isCompleted ? 'none' : '4 4'

        return (
          <g key={p.id} className={`connector-group ${p.isActive ? 'active' : ''}`}>
            {/* Background halo */}
            <path
              d={p.d}
              fill="none"
              stroke="#FFFFFF"
              strokeWidth={strokeWidth + 2}
              strokeOpacity="0.8"
            />
            {/* Main line */}
            <path
              d={p.d}
              fill="none"
              stroke={strokeColor}
              strokeWidth={strokeWidth}
              strokeDasharray={strokeDash}
              strokeLinecap="round"
            />
            {/* Subtle active pulse animation */}
            {p.isActive && (
              <circle r="3.5" fill="#F95924">
                <animateMotion path={p.d} dur="2.4s" repeatCount="indefinite" />
              </circle>
            )}
          </g>
        )
      })}
    </svg>
  )
}
