# Local small-molecule fixtures

These logs were sanitized locally from existing calculations. They are numerical
parser/regression examples, not new calculations or scientific acceptance runs.

| File | Source type | Method |
|---|---|---|
| `water_opt_freq.log` | Existing water optimization/frequency smoke result | B3LYP/STO-3G, gas phase |
| `butane_anti_freq.log` | Existing anti n-butane frequency result | omega-B97XD/def2-SVP, gas phase |
| `butane_gauche_freq.log` | Existing gauche n-butane frequency result | omega-B97XD/def2-SVP, gas phase |
| `error_l9999.log`, `error_l502.log`, `incomplete.log` | Synthetic termination fragments | No calculation |

The sanitizer replaces paths, archive-block hosts/users, and process IDs. For
all three real logs, cclib's complete SCF-energy, frequency, coordinate and
vibrational-displacement arrays were identical before and after sanitization.
Review free-text titles and identifiers before publishing any new fixture.

CREST/xTB tests currently use synthetic text/XYZ snippets. No real CREST fixture
is claimed; add an eligible small-molecule result after L1 acceptance. CREST
3.0.2's `cregen_econf_list` writes relative kcal/mol to `crest.energies`; absolute
Hartree energies are in XYZ comments.

Private tests: set `AG_LOCAL_FIXTURES` to an external directory with exactly three
`ts*.log` files and optional `irc*.log` files. An optional matching
`tsN.review.json` contains `source_sha256`, `confirmed`, and `expected_pairs`
from a previously accepted human mode review. Neither these logs nor the review
metadata belong in this repository. The tests contain no research-specific
numbers or molecule identities.

Thermochemistry uses GoodVibes 4.3.0 with explicit unit frequency/ZPE scaling,
Grimme entropy and Head-Gordon enthalpy correction (100 cm^-1 defaults), 298.15 K
and 1 mol/L. Populations cover only the supplied inputs; degeneracy is explicit.
The reported weighted mean G is the arithmetic population-weighted mean, not
`-RT ln Z`. SPC adds `E_SP - E_frequency` to H, qh-H and qh-G, leaving ZPE intact.

The GoodVibes integration was informed by the old
`auto_g16/thermochemistry/_goodvibes.py`, then rewritten using the installed
4.3.0 `ThermoOptions` / `calc_bbe.from_options` API. No old module is imported.
