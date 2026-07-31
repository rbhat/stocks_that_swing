# Unified dashboard plan

## Outcome

Expose one dashboard at `http://127.0.0.1:8010`:

- Swing Ranking v1 remains the default landing page at `/`.
- A `Legacy` item in the primary navigation opens legacy views in the same
  shell and browser tab under `/legacy`.
- One Google OAuth callback, session cookie, sign-out action, and audit trail
  cover both sets of views.
- Operators open one IAP tunnel. Port 8000 is retained only during migration
  as a rollback path, then removed from `open_remote.sh`.

## Decision

Build the legacy views into the v1 application; do not reverse-proxy the
recovered legacy SPA under `/legacy`.

The recovered bundle has no source maps or editable frontend source and uses
absolute `/api`, `/auth`, and `/assets` paths. A transparent subpath proxy would
collide with v1 routes and would also require fragile rewriting of OAuth
redirects and cookie paths. The recovered backend source is small and intact,
so namespacing its readers and rebuilding its views in the maintained v1 React
shell is the lower-risk path.

## Target routes

The existing v1 routes remain unchanged:

- `/` — v1 overview
- `/forward` and `/forward/:cohort` — v1 forward book
- `/backtests` and `/backtests/:window` — v1 backtests

Legacy routes use a dedicated namespace:

- `/legacy` — legacy overview
- `/legacy/forward/:family` — H1/H2 ledger
- `/legacy/backtests` and `/legacy/backtests/:family` — legacy studies
- `/legacy/config` — redacted configuration and allowlisted settings
- `/legacy/jobs` — job state and sync status

The frontend navigation should place `Legacy` beside the existing v1 items,
not in the account/action area. Legacy pages retain a visible `Legacy` label so
operators cannot confuse the retired books with the v1 forward book.

## Backend boundary

Port the recovered read and control modules into
`src/sts/swing_ranking/dashboard/legacy/`. Expose them through
`/api/legacy/*`; do not import the old `sts.dashboard` package or serve its
compiled SPA.

Initial API mapping:

| Old endpoint | Unified endpoint |
|---|---|
| `/api/overview` | `/api/legacy/overview` |
| `/api/forward/{family}` | `/api/legacy/forward/{family}` |
| `/api/backtests` | `/api/legacy/backtests` |
| `/api/backtests/{family}` | `/api/legacy/backtests/{family}` |
| `/api/config` | `/api/legacy/config` |
| `/api/jobs` | `/api/legacy/jobs` |
| `/api/sync` | `/api/legacy/sync` |
| `/api/sync/{id}` | `/api/legacy/sync/{id}` |
| `/api/config/safe` | `/api/legacy/config/safe` |

All endpoints use the v1 `AuthMiddleware` and session. Read routes require a
valid session. Mutating routes remain admin-only and append to the unified
audit log with a `legacy` scope.

## Data and write safety

The new dashboard container needs explicit mounts for the legacy root:

- `~/sts/ledger` -> `/app/legacy/ledger:ro`
- `~/sts/runs` -> `/app/legacy/runs:ro`
- `~/sts/logs` -> `/app/legacy/logs:ro` for the read-only milestone
- `~/sts/configs` -> `/app/legacy/configs:ro` for the read-only milestone

Ship read-only parity first. Preserve configuration edits and manual sync on
the port-8000 rollback dashboard until a separate admin milestone adds only
the minimum required writable paths. Do not weaken the v1 run/config mounts,
and do not let legacy modules import or invoke the v1 scheduler.

For the admin milestone:

- mount only the legacy settings file and legacy dashboard log directory
  writable;
- keep the existing allowlist validation from `safe_config.py`;
- run sync through a narrowly scoped command/sidecar rather than giving the
  dashboard broad access to secrets or Docker;
- test viewer `403`, admin success, validation failure, lock contention, and
  audit records before enabling either mutation.

## Migration phases

### 1. Freeze and characterize

- Capture authenticated JSON fixtures from each legacy GET endpoint.
- Record empty, corrupt, and representative H1/H2 ledger cases.
- Record the current legacy navigation, field labels, and admin operations.
- Keep the port-8000 app unchanged as the comparison and rollback target.

Exit criterion: fixtures cover every legacy view and the live legacy service
remains available.

### 2. Port the read layer

- Move the recovered legacy data readers into the maintained package with
  explicit legacy-root arguments.
- Add `/api/legacy/*` read routes.
- Mount legacy ledger, runs, logs, and configs read-only in local and remote
  Compose configurations.
- Compare normalized responses from the old and new endpoints using the frozen
  fixtures and live VM data.

Exit criterion: overview, H1/H2 forward, backtests, config, and jobs responses
match the legacy service for all decision-relevant fields.

### 3. Build integrated legacy views

- Add `Legacy` to the primary v1 navigation.
- Implement `/legacy` routes with the existing v1 components, typography,
  loading/error states, chart conventions, and responsive layout.
- Keep terminology and family labels faithful to the legacy books.
- Remove the current external-port URL from `/api/overview`; the navigation is
  now an internal route.

Exit criterion: an authenticated operator can traverse all read-only legacy
views without leaving port 8010 or signing in again.

### 4. Restore bounded admin operations

- Port allowlisted legacy configuration updates and sync status/control.
- Add the minimum writable mounts and scoped runner described above.
- Extend audit events with the target legacy resource and before/after values.

Exit criterion: admin behavior matches the old dashboard, viewer mutations are
rejected, and the v1 scheduler/read-only data boundary remains unchanged.

### 5. Cut over and retire port 8000

- Deploy the unified image while keeping the legacy container running.
- Canary all routes and OAuth on port 8010.
- Remove the second `-L` forward and legacy readiness probe from
  `deploy/open_remote.sh` only after parity and admin checks pass.
- Stop, but do not immediately delete, the legacy container. Retain its image
  tag and `~/sts` data for rollback through an agreed retention window.
- Update deployment docs and remove `STS_LEGACY_DASHBOARD_URL`.

Exit criterion: `open_remote.sh` exposes only 8010, v1 is the default, the
Legacy nav route is complete, and rollback has been rehearsed.

## Verification matrix

- One OAuth login reaches both v1 and legacy routes; one logout invalidates
  both.
- Anonymous page requests redirect to `/login`; anonymous APIs return `401`.
- Viewer/admin permissions are identical across both route families.
- `/` always renders v1; `/legacy` never falls through to a v1 placeholder.
- Direct loads and browser back/forward work for every legacy route.
- Legacy API parity tests compare old and unified responses.
- Missing/corrupt legacy files degrade to empty/error states rather than 500s.
- V1 mounts and legacy read mounts remain read-only until the bounded admin
  milestone.
- `open_remote.sh --stop` leaves no SSH listener after the final cutover.

## Rollback

Until the final retention window expires, rollback is to restart the existing
legacy container and restore the port-8000 forward. No migration phase moves or
rewrites the legacy ledger; the unified application reads the same host data,
so rollback does not require a data conversion.
