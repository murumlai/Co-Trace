// @vitest-environment jsdom

import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import TerminalViewer from './TerminalViewer'

describe('TerminalViewer reference navigation', () => {
  beforeEach(() => {
    Element.prototype.scrollIntoView = vi.fn()
  })

  test('consumes repeated reference requests without clearing later search text', () => {
    const { rerender } = render(
      <TerminalViewer text={'first\nsecond match\nthird'} focusRequest={{ line: 2, requestId: 1 }} />,
    )
    const search = screen.getByLabelText('Filter log lines')
    fireEvent.change(search, { target: { value: 'match' } })

    expect(search.value).toBe('match')
    rerender(<TerminalViewer text={'first\nsecond match\nthird'} focusRequest={{ line: 2, requestId: 2 }} />)
    expect(search.value).toBe('match')
    expect(Element.prototype.scrollIntoView).toHaveBeenCalled()
  })
})