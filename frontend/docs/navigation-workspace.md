# Workspace navigation 0.27

This local frontend revision consolidates the twelve top-level entries into Projects,
Calculations, Analysis, and Monitor, with Settings below the main navigation.
It does not connect V31 execution or alter scientific authority.

## User paths

- Projects retains native projects and historical directory collections with explicit source
  labels. Source and calculation/test-purpose filters replace separate archive/test navigation.
- Calculations contains one drafts destination (browser input/repair revisions and service
  next-stage drafts, separately labeled), prepared/queued tasks, and execution history. Execution history is the first subpage
  and the default destination when opening Calculations.
  New calculation is a fixed header action. The queue remains global and is labeled as such.
- Analysis contains a flat result index, candidate comparison, IRC, and thermochemistry.
  Select results from project/native/history/result lists and open the exact selection in
  comparison; selection can span pages. Selected G values can use the existing Boltzmann
  helper after explicit comparability, temperature and selected-set confirmation.
- Settings contains data/library configuration and actual capability/version reporting.
  Scientific test/acceptance collections remain under Projects, not application settings.

All records use the same archive or attempt detail route. Structure/results is the default tab and includes the summary, conditions, structure and
frequencies together; the other tabs are Execution/diagnostics and Provenance/records. Source jumps open
execution/log view; scientific review links open provenance. Heavy views mount on first
visit and remain mounted inside the detail so pending review command identity is preserved.
Execution timeline, stage evidence and historical receipt details remain available through
public query endpoints. Execution success and scientific acceptance are never combined.

Export, annotation and repair forms are accessible native modal drawers with Escape and
focus return. Notes remain manual, unverified references. Repair drafts retain original
result references. No input, review, Core identity, library object or queue item is migrated.
Browser drafts use the existing IndexedDB database; temporary unsaved inputs and list/detail
preferences use session storage. Storage-disabled behavior remains explicit where saving
is required. Back-to-list links preserve URL context, existing filters, selection and scroll.

## Compatibility

Legacy hash paths redirect with replaceState, preserving query parameters:
`drafts` → calculations/new, `task-center` → calculations/drafts,
`workflows` → calculations/runs, `screening` → analysis/compare,
`results` → analysis/results, `offline-science` → analysis/irc,
`library` and `capabilities` → settings subpages, `tests` → projects/test,
and archive index → projects/historical. Exact archive and attempt URLs are unchanged.
Old external links continue to work; browser history is not padded by redirects.

## Validation and operating limits

Synthetic browser suites cover route/context preservation, source-bound detail navigation,
readonly browsing, draft version/backup recovery, separate storage identities, modal focus,
comparison gates, scientific facts and mobile layout. Python boundary and operation tests
retain readonly APIs and uncertain-submit no-replay behavior. Installation uses a frozen
local wheel and verifies installed bytes. Local read-only acceptance is on the existing
origin; no scientific execution is part of the release.

IRC still requires an explicit trajectory interchange file. GoodVibes still imports a
prepared table. Selection labels do not prove imported files correspond to a chosen result.
Historical directory grouping is presentation only, not a native Project/Task binding.

## Release verification

Version `0.27.0+local.1` passed 162 distinct browser cases across the required fixture
configurations (latest successful outcome per named case, not a sum of overlapping runs),
31 installed-package Python API/boundary/operation tests, TypeScript and Vite build.
The installed frontend and backend files matched their frozen wheel receipts. Real-browser
acceptance passed on the preview and the normal 8767 origin, with API writes blocked,
no page errors, no failing API responses, and no horizontal overflow at 390 px. All 570
snapshotted original source files retained their hashes and recorded filesystem metadata.

The shared read budget retains its slot until an active transport settles even if the
view cancels its subscription; an independent 15-second timeout bounds that transport.
This prevents cancelled navigation from briefly exceeding the two-request budget.
The result index remounts on library revision changes so a newly captured archive appears
without a full page reload. Dedicated library, conditions and no-token suites passed.

Local artifacts and rollback state live outside source control under the installation's
`navigation-upgrade` directory. The previous environment and launcher backups are retained.

## 0.27.0+local.2 follow-up

Merged Overview into Structure/results, preserving old `view=overview` links and saved
preferences as aliases for the combined default page. Calculations now opens Run/history
by default, with that tab first; explicit drafts, new-calculation and queue links still work.

Validation: 37 distinct affected browser cases passed across the follow-up runs, including
9 navigation/layout cases against the final installed package. TypeScript, Vite build and
installed-byte verification passed. The final package includes both requested changes.

## Project management 0.28.0+local.1

The project catalog, result scope, breadcrumbs, and comparison picker now share the
same name-based collections. A project such as b5 contains its task directories; the
project selector offers b5 once, with a separate task selector for narrower browsing.
Project titles link to their aggregate results. Source kind and source label remain
separate, and original records are unchanged.

Project cards expose pin and rename/organization controls. Preferences reuse the
existing browser-local organization store; pin priority applies before every sort and
before pagination. Collection links use a stable member anchor rather than the display
name, and previous name-based series links remain recognized. Storage failures are
reported explicitly. Preferences are local to the browser, not shared server metadata.

Comparison supports multiple project scopes and retains typed result references while
changing projects or pages and after reload. It deduplicates identical kind/id pairs;
comparison caches also include source kind. The selected-results list allows removal
and clearing. Partial task-index failures are explicit. Conditions, composition, energy
and manual confirmation gates remain in force; membership does not establish scientific
comparability. Archived detail links retain their own source task identity.

Optimization analysis displays the current 3D frame on the left and energy/convergence
plots on the right above 1000 px. Small screens stack these panels. All three views use
the same selected complete optimization cycle; segments and original-source links are
preserved.

Validation: TypeScript/Vite build and 28 affected browser regressions passed, including
project/task hierarchy, pin priority, rename/reload/link continuity, cross-project checked
results, deduplication, request budget, source identity and desktop/mobile plot layout.
The installed package byte verification passed. Real-data preview acceptance verified
b5's 11 task directories and 11 distinct archived results, selection across b5 and c4,
and a 19-step trajectory with side-by-side structure/plots. API writes were blocked.
