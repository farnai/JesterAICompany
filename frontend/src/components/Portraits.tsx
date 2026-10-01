import React from 'react'

interface PortraitProps {
  role: string
  size?: number
  className?: string
}

export const RolePortrait: React.FC<PortraitProps> = ({ role, size = 48, className = '' }) => {
  const normRole = role.toLowerCase().replace(/[\s-]/g, '_')

  switch (normRole) {
    case 'owner':
    case 'founder':
      return (
        <svg
          width={size}
          height={size}
          viewBox="0 0 48 48"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          className={className}
          data-testid="portrait-owner"
        >
          <circle cx="24" cy="24" r="22" fill="#FFF2EB" stroke="#F95924" strokeWidth="2" />
          {/* Founder: confident, crisp tailored collar, warm hair */}
          <path d="M16 19C16 14.5817 19.5817 11 24 11C28.4183 11 32 14.5817 32 19V22C32 26.4183 28.4183 30 24 30C19.5817 30 16 26.4183 16 22V19Z" fill="#F0C6A5" />
          <path d="M15 17C15 12 19 9 24 9C29 9 33 12 33 17C30 15 27 15 24 16C21 17 18 16 15 17Z" fill="#3D291F" />
          {/* Eyes & smile */}
          <circle cx="20.5" cy="21" r="1.5" fill="#2E231D" />
          <circle cx="27.5" cy="21" r="1.5" fill="#2E231D" />
          <path d="M22 25.5C22.8 26.3 25.2 26.3 26 25.5" stroke="#9E694D" strokeWidth="1.2" strokeLinecap="round" />
          {/* Shoulders & blazer with orange collar accent */}
          <path d="M11 41C11 34.5 16 33 24 33C32 33 37 34.5 37 41" fill="#1E293B" />
          <path d="M21 33L24 38L27 33" fill="#F95924" />
        </svg>
      )

    case 'ceo':
      return (
        <svg
          width={size}
          height={size}
          viewBox="0 0 48 48"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          className={className}
          data-testid="portrait-ceo"
        >
          <circle cx="24" cy="24" r="22" fill="#F4F4F0" stroke="#71716A" strokeWidth="2" />
          {/* CEO: focused executive haircut, dark blazer, tie */}
          <path d="M16 20C16 15.5 19.5 12 24 12C28.5 12 32 15.5 32 20V22C32 26.5 28.5 30 24 30C19.5 30 16 26.5 16 22V20Z" fill="#E8C39E" />
          <path d="M15 18C15 12 19 10 24 10C29 10 33 12 33 18C31 16 28 15 24 15C20 15 17 16 15 18Z" fill="#1C1C1A" />
          <circle cx="20.5" cy="21" r="1.5" fill="#1C1C1A" />
          <circle cx="27.5" cy="21" r="1.5" fill="#1C1C1A" />
          <path d="M22 26C23 26.8 25 26.8 26 26" stroke="#8C6747" strokeWidth="1.2" strokeLinecap="round" />
          <path d="M10 41C10 34 15.5 33 24 33C32.5 33 38 34 38 41" fill="#2C3437" />
          <path d="M22 33L24 39L26 33" fill="#FFFFFF" />
          <path d="M23.2 36L24 41L24.8 36" fill="#F95924" />
        </svg>
      )

    case 'developer':
      return (
        <svg
          width={size}
          height={size}
          viewBox="0 0 48 48"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          className={className}
          data-testid="portrait-developer"
        >
          <circle cx="24" cy="24" r="22" fill="#EFF6FF" stroke="#3B82F6" strokeWidth="2" />
          {/* Developer: modern spectacles, headphones, teal sweater */}
          <path d="M16 20C16 15.5 19.5 12 24 12C28.5 12 32 15.5 32 20V22C32 26.5 28.5 30 24 30C19.5 30 16 26.5 16 22V20Z" fill="#F6D4B7" />
          <path d="M15 18C16 11 20 10 24 10C28 10 32 11 33 18C30 16 27 16 24 16C21 16 18 16 15 18Z" fill="#3B2E2A" />
          {/* Modern square specs */}
          <rect x="18" y="19" width="5" height="4" rx="1" stroke="#1E293B" strokeWidth="1.4" fill="rgba(255,255,255,0.4)" />
          <rect x="25" y="19" width="5" height="4" rx="1" stroke="#1E293B" strokeWidth="1.4" fill="rgba(255,255,255,0.4)" />
          <line x1="23" y1="21" x2="25" y2="21" stroke="#1E293B" strokeWidth="1.4" />
          {/* Shoulders */}
          <path d="M10 41C10 34 16 33 24 33C32 33 38 34 38 41" fill="#0D9488" />
        </svg>
      )

    case 'qa_engineer':
    case 'qa':
      return (
        <svg
          width={size}
          height={size}
          viewBox="0 0 48 48"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          className={className}
          data-testid="portrait-qa"
        >
          <circle cx="24" cy="24" r="22" fill="#ECFDF5" stroke="#10B981" strokeWidth="2" />
          {/* QA Engineer: sharp inspecting gaze, magnifying loop/stylus badge, emerald polo */}
          <path d="M16 20C16 15.5 19.5 12 24 12C28.5 12 32 15.5 32 20V22C32 26.5 28.5 30 24 30C19.5 30 16 26.5 16 22V20Z" fill="#F3CBAB" />
          <path d="M15 17C17 11 22 10 26 10C30 10 33 13 33 18C30 17 26 16 23 16C20 16 17 16 15 17Z" fill="#4B382A" />
          <circle cx="20.5" cy="21" r="1.5" fill="#1C1C1A" />
          <circle cx="27.5" cy="21" r="1.5" fill="#1C1C1A" />
          <path d="M22 26C23 26.5 25 26.5 26 26" stroke="#8C6747" strokeWidth="1.2" strokeLinecap="round" />
          <path d="M10 41C10 34 16 33 24 33C32 33 38 34 38 41" fill="#047857" />
          {/* Verification check emblem */}
          <circle cx="32" cy="34" r="5" fill="#10B981" />
          <path d="M30 34L31.5 35.5L34 33" stroke="#FFFFFF" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      )

    case 'product_manager':
    case 'product':
      return (
        <svg
          width={size}
          height={size}
          viewBox="0 0 48 48"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          className={className}
          data-testid="portrait-pm"
        >
          <circle cx="24" cy="24" r="22" fill="#FEF3C7" stroke="#F59E0B" strokeWidth="2" />
          <path d="M16 20C16 15.5 19.5 12 24 12C28.5 12 32 15.5 32 20V22C32 26.5 28.5 30 24 30C19.5 30 16 26.5 16 22V20Z" fill="#E8C39E" />
          <path d="M15 17C17 11 23 9 29 11C33 13 33 17 33 18C30 17 26 16 23 16C19 16 16 17 15 17Z" fill="#1E293B" />
          <circle cx="20.5" cy="21" r="1.5" fill="#1C1C1A" />
          <circle cx="27.5" cy="21" r="1.5" fill="#1C1C1A" />
          <path d="M22 25.5C23 26.2 25 26.2 26 25.5" stroke="#8C6747" strokeWidth="1.2" strokeLinecap="round" />
          <path d="M10 41C10 34 16 33 24 33C32 33 38 34 38 41" fill="#6366F1" />
        </svg>
      )

    case 'researcher':
    case 'research':
      return (
        <svg
          width={size}
          height={size}
          viewBox="0 0 48 48"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          className={className}
          data-testid="portrait-researcher"
        >
          <circle cx="24" cy="24" r="22" fill="#F3E8FF" stroke="#A855F7" strokeWidth="2" />
          <path d="M16 20C16 15.5 19.5 12 24 12C28.5 12 32 15.5 32 20V22C32 26.5 28.5 30 24 30C19.5 30 16 26.5 16 22V20Z" fill="#F2CBB0" />
          <path d="M15 18C15 11 20 9 24 9C28 9 33 11 33 18C30 16 27 16 24 16C21 16 18 16 15 18Z" fill="#581C87" />
          <circle cx="20" cy="20.5" r="3" stroke="#581C87" strokeWidth="1.2" fill="rgba(255,255,255,0.3)" />
          <circle cx="28" cy="20.5" r="3" stroke="#581C87" strokeWidth="1.2" fill="rgba(255,255,255,0.3)" />
          <line x1="23" y1="20.5" x2="25" y2="20.5" stroke="#581C87" strokeWidth="1.2" />
          <path d="M10 41C10 34 16 33 24 33C32 33 38 34 38 41" fill="#7E22CE" />
        </svg>
      )

    case 'designer':
    case 'ux_designer':
    case 'ux':
      return (
        <svg
          width={size}
          height={size}
          viewBox="0 0 48 48"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          className={className}
          data-testid="portrait-designer"
        >
          <circle cx="24" cy="24" r="22" fill="#FFF1F2" stroke="#F43F5E" strokeWidth="2" />
          <path d="M16 20C16 15.5 19.5 12 24 12C28.5 12 32 15.5 32 20V22C32 26.5 28.5 30 24 30C19.5 30 16 26.5 16 22V20Z" fill="#F5C6A8" />
          <path d="M15 17C18 11 23 9 27 10C31 11 34 14 34 19C30 17 26 17 22 17C19 17 16 17 15 17Z" fill="#BE123C" />
          <circle cx="20.5" cy="21" r="1.5" fill="#1C1C1A" />
          <circle cx="27.5" cy="21" r="1.5" fill="#1C1C1A" />
          <path d="M22 25.5C23 26.2 25 26.2 26 25.5" stroke="#8C6747" strokeWidth="1.2" strokeLinecap="round" />
          <path d="M10 41C10 34 16 33 24 33C32 33 38 34 38 41" fill="#E11D48" />
        </svg>
      )

    case 'marketing_specialist':
    case 'marketing':
      return (
        <svg
          width={size}
          height={size}
          viewBox="0 0 48 48"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          className={className}
          data-testid="portrait-marketing"
        >
          <circle cx="24" cy="24" r="22" fill="#FFFBEB" stroke="#D97706" strokeWidth="2" />
          <path d="M16 20C16 15.5 19.5 12 24 12C28.5 12 32 15.5 32 20V22C32 26.5 28.5 30 24 30C19.5 30 16 26.5 16 22V20Z" fill="#ECC39E" />
          <path d="M15 17C16 12 20 10 24 10C28 10 32 12 33 17C30 16 27 15 24 15C21 15 18 16 15 17Z" fill="#78350F" />
          <circle cx="20.5" cy="21" r="1.5" fill="#1C1C1A" />
          <circle cx="27.5" cy="21" r="1.5" fill="#1C1C1A" />
          <path d="M22 25.5C23 26.2 25 26.2 26 25.5" stroke="#8C6747" strokeWidth="1.2" strokeLinecap="round" />
          <path d="M10 41C10 34 16 33 24 33C32 33 38 34 38 41" fill="#B45309" />
        </svg>
      )

    default:
      return (
        <svg
          width={size}
          height={size}
          viewBox="0 0 48 48"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          className={className}
          data-testid="portrait-default"
        >
          <circle cx="24" cy="24" r="22" fill="#F1F1EC" stroke="#A8A89E" strokeWidth="2" />
          <circle cx="24" cy="20" r="8" fill="#D3D3C9" />
          <path d="M12 40C12 34 17 33 24 33C31 33 36 34 36 40" fill="#A8A89E" />
        </svg>
      )
  }
}
