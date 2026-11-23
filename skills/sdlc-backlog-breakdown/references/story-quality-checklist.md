# Story quality checklist

## INVEST
- [ ] Independent: can be built and released without another unfinished story (or dependency is explicit)
- [ ] Negotiable: describes the outcome, not the implementation
- [ ] Valuable: a user, operator, or the business can observe the benefit
- [ ] Estimable: the team could size it; otherwise create a spike
- [ ] Small: fits in 1 to 3 days, never more than one sprint
- [ ] Testable: acceptance criteria are checkable

## Definition of Ready
- [ ] User story statement present (As a / I want / So that)
- [ ] 2 or more Given/When/Then criteria, including one error/negative case
- [ ] `req_refs` and `design_ref` filled in
- [ ] Dependencies and blockers listed
- [ ] Security/privacy implications noted (authz rule, data sensitivity)
- [ ] UI states noted when frontend work is involved (loading, empty, error, denied)
- [ ] Estimate and priority set

## Definition of Done (reference for acceptance)
- [ ] Code reviewed and merged via PR linked to the issue
- [ ] Unit/integration tests added; migrations tested up and, where feasible, down
- [ ] CI green including security scans
- [ ] Observability added (logs/metrics) for new behavior
- [ ] Docs/OpenAPI updated

## Good vs bad examples
Bad: "Implement preferences table." (layer, not value)
Good: "As a customer, I want to choose which emails I receive, so that I only get relevant messages."

Acceptance criteria (good):
- Given a signed-in user, When they save preferences, Then the choices persist and show on reload.
- Given an unauthenticated request, When it calls the preferences endpoint, Then it receives 401.
- Given an invalid category, When saved, Then the API returns 400 ProblemDetails and the form shows the error.
