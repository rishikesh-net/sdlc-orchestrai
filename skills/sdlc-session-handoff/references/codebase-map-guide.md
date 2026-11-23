# Building and refreshing the codebase map

Goal: let any client understand the repo in minutes without a full scan, and refresh only what changed.

## How to build (first time)
1. List tracked files by area: `git ls-files | head -300`, then group by top-level folder.
2. Read manifests and entry points only: solution/project files, `Program.cs`/startup, `package.json`, `vite.config.*`,
   migrations folder, CI workflows, README. Skim, do not read every file.
3. Fill `templates/codebase-map.md.tmpl`. Keep each section to a few lines with file paths as pointers.
4. Run `sdlc-state.sh map-stamp` to record the commit.

## Sections to capture
- Solution/projects and layering (API, Application, Domain, Infrastructure, tests)
- API surface: route groups or controllers, versioning, auth scheme, error model
- Database: schema/migration location, key tables, naming, how migrations run
- Frontend: app structure, routing, state/data fetching, API client generation, env handling
- Auth and authorization: where policies live, token validation, roles/claims
- Cross-cutting: logging, config/secrets handling, background jobs
- Build, test, lint, and run commands
- Conventions worth knowing (naming, folder rules, PR/commit style)
- Known hazards ("do not touch" areas, flaky tests, generated code)

## How to refresh
1. `sdlc-state.sh map-status` lists changed paths since the stamp.
2. Re-read only those paths (and their neighbors if structure changed). Update only affected sections.
3. `sdlc-state.sh map-stamp`.
4. If more than about a third of the repo changed, rebuild instead of patching.

## Style
Short, factual, path-based. Prefer "Auth policies: src/Api/Security/Policies.cs" over prose. Never include secrets or sample credentials.
