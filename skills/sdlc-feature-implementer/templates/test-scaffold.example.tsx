import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { NotificationPreferencesForm } from './NotificationPreferencesForm';

/**
 * Acceptance tests for Story: E1-S1
 * Requirement: REQ-001
 * Design Ref: docs/design/feature.md#7-frontend-react
 */
describe('NotificationPreferencesForm', () => {
  it('saves preferences and displays success message when valid options selected', async () => {
    // AC: Given a signed-in customer, When they save preferences, Then choices persist and appear on reload [REQ-001]
    const onSave = vi.fn().mockResolvedValue({ success: true });
    render(<NotificationPreferencesForm onSave={onSave} initialCategories={['marketing']} />);

    const marketingCheckbox = screen.getByRole('checkbox', { name: /marketing/i });
    expect(marketingCheckbox).toBeChecked();

    const submitButton = screen.getByRole('button', { name: /save preferences/i });
    fireEvent.click(submitButton);

    await waitFor(() => {
      expect(onSave).toHaveBeenCalledWith(['marketing']);
      expect(screen.getByText(/preferences updated successfully/i)).toBeInTheDocument();
    });
  });

  it('displays validation error if an invalid selection is submitted', async () => {
    // AC: Given an unknown category, When saved, Then the form shows the error [REQ-001]
    const onSave = vi.fn().mockRejectedValue(new Error('Invalid category'));
    render(<NotificationPreferencesForm onSave={onSave} initialCategories={[]} />);

    const submitButton = screen.getByRole('button', { name: /save preferences/i });
    fireEvent.click(submitButton);

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(/invalid category/i);
    });
  });
});
