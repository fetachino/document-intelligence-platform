import React from 'react'
import { render, screen } from '@testing-library/react'
import { describe, expect, test } from 'vitest'
import App from './App'

describe('App', () => {
  test('renders heading, file input, and upload button', () => {
    render(<App />)

    expect(
      screen.getByRole('heading', {
        name: /Document Intelligence Platform/i,
      }),
    ).toBeInTheDocument()

    const fileInput = document.querySelector('input[type="file"]')
    expect(fileInput).toBeInTheDocument()

    expect(
      screen.getByRole('button', { name: /upload/i }),
    ).toBeInTheDocument()
  })
})