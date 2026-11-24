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
