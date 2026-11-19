---
name: testing
description: Testing for the qa-cert-wrapper workspace (Playwright + TypeScript, Service Object Model, API-тесты (qa-api-tests)) — tests ship in the same MR as the code, placed seam-first, following each repo's existing spec conventions. Use when implementing any feature or fix, when writing or changing tests, or when deciding where a test belongs and whether one is needed. Runner is `npx playwright test` — never the watch-mode test command, which hangs agent sessions. The ticket itself is routed by feature or bugfix; they load this skill for the test part. Use it directly when the question is only about tests.
---

## Parameters

| Placeholder | Meaning | Reference value (Acme) |
|---|---|---|
| qa-cert-wrapper | Name of the outstaff workspace | Acme |
| Playwright + TypeScript, Service Object Model, API-тесты (qa-api-tests) | One-line tech stack summary | NestJS + SST/AWS + React |
| npx playwright test | Non-watch test command | yarn test:run |
| none | Coverage command, where a repo defines one | yarn test:cov |
| none | Command that activates the repo's pinned runtime version | nvm use |

# testing — tests with the code, seam-first

## The rule

Tests ship with the code — same MR, in whatever order you write them. No test-first
ceremony: what matters is that every behavior change lands with a test that would fail
without it, and that the repo's full suite is green before mr.md.

One exception, deliberate: **bug fixes start with a failing reproduction test** before
any fix — that is evidence for the diagnosis, not process; the bugfix skill owns it.

What does *not* need a test: infrastructure/deploy config, module wiring and DI glue,
frontend layout/styles, one-off scripts and migrations. "No test" never means "no
verification" — typecheck, lint, a dev deploy, or eyes on the screen, per verify.

## Seams — where tests go

A seam is the public boundary you observe behavior through. Tests live at seams, never
against internals — internals change on refactor, behavior shouldn't. In a typical
service stack the seams usually are:

- **service/module public methods** — the default unit seam; test doubles only at the
  repository/external-client boundary, not for internal collaborators;
- **HTTP/API endpoints** (request-level test harness) — when the contract itself is the
  change;
- **event/message handlers** — invoked directly with a constructed payload matching the
  real event shape;
- **repository/data-access methods** — when the change is the data-access pattern
  itself; assert against the documented patterns in `data/<service>.md`.

You cannot test everything — put the effort on critical paths, not on every getter.

## Follow the repo's conventions

Tests are a client-visible deliverable in the MR. Before writing the first one, read a
couple of neighboring test files and match them: suite/case structure, fixture style,
naming, how doubles are built. Do not import a personal testing style into a client
repo — a test that looks foreign draws review comments the fix itself wouldn't.

## Test quality (the tells)

- **Implementation-coupled** — breaks on refactor though behavior didn't change; mocks
  internal collaborators or peeks at private state.
- **Mock-testing** — the assertion is about the mock (`toHaveBeenCalledWith`) when a real
  behavior assertion was available.
- **Side-channel verification** — querying the datastore directly instead of going
  through the interface under test (unless the repository IS the seam).
- **Tautological** — expected values recomputed the same way the code computes them; take
  them from an independent source (a worked example, the ticket).

## Does the test actually catch anything?

A test written after the code passes immediately — which proves nothing by itself. Where
it matters (regression tests, review-fix tests), spend the 30 seconds: stash the fix,
run the test, watch it fail, restore. verify has the full gate.

## Workspace specifics

- `npx playwright test` runs the suite once, non-interactively. Single file:
  `npx playwright test path/to/test-file`. Coverage where defined: `none`.
  **Invariant: the test command must be non-watch — watch mode hangs agent sessions.**
  The interactive/watch variant of the test script is taboo in sessions.
- Fixtures carry real-shaped domain keys (e.g. tenant/account scoping where the domain
  is multi-tenant) — an unscoped fixture tests a world that doesn't exist; shapes are in
  `data/<service>.md`.
- `none` before the first run — a wrong runtime version fails suites in
  misleading ways.
