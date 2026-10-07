/// <reference types="@testing-library/jest-dom" />
import '@testing-library/jest-dom'

// Mock ResizeObserver for React Flow in jsdom
if (typeof globalThis.ResizeObserver === 'undefined') {
  ;(globalThis as any).ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
}

// Mock DOMMatrixReadOnly for React Flow
if (typeof globalThis.DOMMatrixReadOnly === 'undefined') {
  ;(globalThis as any).DOMMatrixReadOnly = class DOMMatrixReadOnly {
    m22 = 1
    m11 = 1
  }
}

// Polyfill scrollIntoView
if (typeof window !== 'undefined' && window.HTMLElement) {
  window.HTMLElement.prototype.scrollIntoView = function () {}
}

// Default fallback mocks for Step 21 API endpoints so legacy tests do not trigger hanging HTTP fetches
import { vi } from 'vitest'
import { api } from '../api/client'

vi.spyOn(api, 'getCompanyRuns').mockResolvedValue([])
vi.spyOn(api, 'getRepositoryProjects').mockResolvedValue([])

