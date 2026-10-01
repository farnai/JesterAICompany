import { describe, it, expect } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import App from '../App'

describe('STEP 1: React + TypeScript + Vite Frontend Foundation', () => {
  it('renders root application successfully', async () => {
    render(<App />)
    await waitFor(() => {
      expect(screen.getByTestId('app-container')).toBeInTheDocument()
    })
  })
})
