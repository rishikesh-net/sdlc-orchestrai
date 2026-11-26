# Test scaffolding examples

Reference scaffolds for Step 3 of `sdlc-feature-implementer`. Copy the relevant block
into your test project and replace the story/requirement IDs, routes, and component names.
Keep one test per Given/When/Then acceptance criterion and always include a negative case.

## Backend (.NET / C#)

```csharp
using System.Net;
using System.Net.Http.Json;
using FluentAssertions;
using Microsoft.AspNetCore.Mvc.Testing;
using Xunit;

namespace Project.Tests.Features;

/// <summary>
/// Acceptance test scaffold for Story: E1-S1
/// Requirement: REQ-001
/// Design Ref: docs/design/feature.md#6-api-contracts
/// </summary>
public class NotificationPreferencesTests : IClassFixture<WebApplicationFactory<Program>>
{
    private readonly HttpClient _client;

    public NotificationPreferencesTests(WebApplicationFactory<Program> factory)
    {
        _client = factory.CreateClient();
    }

    [Fact]
    public async Task SavePreferences_WhenCustomerIsAuthenticated_PersistsAndReturnsSuccess()
    {
        // AC: Given a signed-in customer, When they save preferences, Then choices persist and appear on reload [REQ-001]

        // Arrange
        var request = new { Category = "marketing", EmailEnabled = true };

        // Act
        var response = await _client.PostAsJsonAsync("/api/v1/customers/preferences", request);

        // Assert
        response.StatusCode.Should().Be(HttpStatusCode.OK);
    }

    [Fact]
    public async Task SavePreferences_WhenUnauthenticated_Returns401Unauthorized()
    {
        // AC: Given an unauthenticated request, When it calls the preferences API, Then it receives 401 [REQ-001]

        // Act
        var response = await _client.PostAsJsonAsync("/api/v1/customers/preferences", new { Category = "marketing" });

        // Assert
        response.StatusCode.Should().Be(HttpStatusCode.Unauthorized);
    }

    [Fact]
    public async Task SavePreferences_WhenCategoryIsUnknown_Returns400ProblemDetails()
    {
        // AC: Given an unknown category, When saved, Then the API returns 400 ProblemDetails [REQ-001]

        // Arrange
        var request = new { Category = "non_existent_category", EmailEnabled = true };

        // Act
        var response = await _client.PostAsJsonAsync("/api/v1/customers/preferences", request);

        // Assert
        response.StatusCode.Should().Be(HttpStatusCode.BadRequest);
        var problem = await response.Content.ReadFromJsonAsync<Microsoft.AspNetCore.Mvc.ProblemDetails>();
        problem.Should().NotBeNull();
        problem!.Title.Should().Contain("Invalid category");
    }
}
```

## Frontend (React / TypeScript)

```tsx
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
```
