# Xiao-Chen Wang group computational precedents

Audit date: 2026-07-14.

## Scope and evidence labels

This audit focuses on the Wang group papers most relevant to borane catalysis,
chiral bisboranes, pyridine functionalization, and borane/transition-metal
cooperative asymmetric catalysis. Publisher Supporting Information (SI) was
read where it was publicly accessible. Copyrighted article and SI PDFs are not
stored in the repository.

- **SI verified**: the computational section and its method statement were
  read in the publisher SI.
- **SI checked - no new DFT section**: the SI table of contents and text were
  searched; any stereochemical model must not be described as a new DFT study.
- **Partial**: a publisher abstract, main article, or indexed note establishes
  a computational contribution, but the complete SI method was not available
  during this audit.

## Paper-by-paper record

| Year | Work | Audit status | What the calculation or evidence addressed |
| --- | --- | --- | --- |
| 2018 | C2-symmetric bicyclic bisborane catalysts, DOI `10.1002/anie.201808289` | Partial | The article reports Gaussian 09 DFT in connection with temperature-dependent formation of kinetic and thermodynamic bisborane diastereomers. The exact SI protocol was blocked by publisher verification and is not recorded as verified. |
| 2019 | Spiro-bicyclic bisboranes for asymmetric quinoline hydrogenation, DOI `10.1002/anie.201900907` | Main article checked | Catalyst identity was supported by adduct crystallography and experiments. No original computational section was found in the accessible main article; it explicitly left the origin of chemoselectivity for further study. |
| 2019 | Hydrosilylation-promoted furan Diels-Alder cascade, DOI `10.1021/jacs.9b11909` | SI verified | Full competing mechanistic energy profiles, TS structures and IRC connectivity for hydride-transfer/cycloaddition pathways. This is a mechanistic precedent, not an asymmetric-selectivity calculation. |
| 2020 | Enantioselective reduction of 2-vinylpyridines, DOI `10.1002/anie.202007352` | Partial | The accessible record establishes a 1,4-hydroboration/transfer-hydrogenation cascade with a chiral spiro-bisborane. No complete computational protocol was verified in this audit. |
| 2021 | Asymmetric vinylogous Mannich reaction, DOI `10.1021/jacs.1c00006` | SI checked - no new DFT section | The SI rationalizes selectivity with catalyst-isoquinoline crystal structures and earlier hydrogenation calculations. It does not present a new enumerated TS study for this reaction. |
| 2022 | Borane-catalyzed C3 alkylation of pyridines, DOI `10.1021/jacs.2c00962` | SI verified | Compared TSs for nucleophilic addition, proton abstraction and oxidative aromatization, and evaluated mono- versus dialkylation. This is a regio/mechanism precedent rather than asymmetric induction. |
| 2022 | C3-selective trifluoromethylthiolation/difluoromethylthiolation, DOI `10.1021/jacs.2c06776` | SI checked - no DFT section | Extensive experimental SI was present, but no Gaussian/DFT/TS section was found. |
| 2023 | Asymmetric C3 allylation of pyridines, DOI `10.1021/jacs.3c03056` | SI checked - no DFT section | The borane/Ir asymmetric method includes experimental mechanistic studies, matched/mismatched experiments and kinetic resolution, but no DFT TS ensemble in the SI. |
| 2023 | C3 cyanation of pyridines, DOI `10.1002/anie.202216894` | Partial | The publisher abstract states that calculations and controls attribute regioselectivity of C2-substituted pyridines to combined electronic and steric effects. The SI method was not accessible, so do not quote a computational protocol from this audit. |
| 2024 | B(C6F5)3-catalyzed tertiary-amine C(sp3)-H alkylation, DOI `10.1021/acscatal.4c01160` | SI verified | Site-selectivity and an asynchronous concerted hydride-transfer/C-C-bond-forming TS were studied; the SI includes IRC evidence and substrate/olefin comparisons. |
| 2024 | Enantioselective alpha-alkylation of 2-alkylbenzoxazoles, DOI `10.1021/jacs.4c09067` | SI verified | DFT compared B(C6F5)3/BF3 coordination and reaction pathways with many TS topologies. The published computational section did not calculate the chiral CAT2 origin of enantioselectivity, so it must not be cited as a complete asymmetric TS model. |
| 2025 | Vinylogous enone addition to allenes by borane/Pd catalysis, DOI `10.1021/jacs.4c16214` | SI checked - no DFT section | The asymmetric method and catalyst characterization are reported, but no computational section was found in the SI. |
| 2025 | Borane/transition-metal allenylic and allylic alkylation, DOI `10.1021/jacs.5c13835` | SI verified | Six TSs were located for the stereodetermining allenylic step with a chiral Ni complex and a borane-bound nucleophile. The favored TS was interpreted through steric organization and multiple C-H...F interactions. |
| 2026 | Asymmetric nitrone [3+2] cycloaddition with spiro-bicyclic bisboranes, DOI `10.31635/ccschem.026.202506952` | Metadata only | Relevant to the future module, but neither a publisher SI computational section nor a method statement was verified during this audit. |

## Verified computational protocols

### JACS 2019, `10.1021/jacs.9b11909`

- Gaussian 09.
- Geometry optimization and frequencies: M06-2X/6-31G(d).
- IRC used to connect minima and TSs.
- Single points: M06-2X/6-311++G(d,p), SMD(toluene), with D3 as stated in the SI.
- Gibbs energies at 383 or 393 K.
- RRHO entropy above 100 cm-1 and free-rotor treatment below 100 cm-1;
  1 atm to 1 mol/L correction implemented with GoodVibes.

### JACS 2022, `10.1021/jacs.2c00962`

- Gaussian 09.
- Geometry optimization and frequencies: omega-B97XD/6-31G(d).
- Single points: omega-B97XD/def2-TZVPP with SMD.
- Minima/TS assignment by zero/one imaginary frequency.
- Gibbs energies at 353.15 K; Grimme low-frequency free-rotor treatment below
  100 cm-1 and 1 atm to 1 mol/L correction through GoodVibes.

### ACS Catalysis 2024, `10.1021/acscatal.4c01160`

- Gaussian 16 Rev. A.03.
- Geometry optimization: B3LYP-D3(BJ)/6-31G(d) with IEFPCM.
- Frequencies at 413.15 K; minima/TS stationary-point classification.
- Single points: omega-B97X-D/6-311++G(2d,p) with SMD.
- Solution Gibbs energies at 413.15 or 298.15 K and 1 mol/L through
  GoodVibes 2.0.3; positive modes below 100 cm-1 raised to 100 cm-1.
- IRC for the key TS supported an asynchronous concerted sequence: hydride
  transfer precedes C-C bond formation along the path.

### JACS 2024, `10.1021/jacs.4c09067`

- Gaussian 09.
- Geometry optimization and frequencies: omega-B97XD/6-31G(d) with SMD.
- Single points: omega-B97XD/def2-TZVPP with SMD.
- Thermal corrections at 298.15 K.
- IRC used to determine minima/TS connectivity.
- Multiple BF3 and B(C6F5)3 coordination/TS arrangements were compared, but
  the chiral bisborane selectivity itself was not calculated.
- The SI coordinate tables give 57 atoms for `BF3-TS1` and 78 atoms each for
  `BF3-TS2-B1` and `BF3-TS2-B2`. The full B(C6F5)3 models are not a smaller
  substitute: the corresponding TS1 contains 87 atoms and TS2-B1 contains 108.
- `BF3-TS1` is the approved first offline benchmark record. The SI reports a
  featured imaginary frequency of 1455.35i cm-1 and Delta G double dagger of
  9.2 kcal/mol; its Cartesian geometry has C-H and N-H distances of 1.4293 and
  1.2842 angstrom along the declared proton-transfer coordinate.
- `BF3-TS2-B1/B2` form the second-stage C-C-forming topology pair. Both are
  labeled 16.9 kcal/mol, with featured imaginary frequencies of 389.10i and
  351.55i cm-1 and C-C distances of 2.1513 and 2.2249 angstrom.
- The SI tables do not provide source-reported charge/multiplicity, complete
  Gaussian routes, an SMD solvent identity in the method paragraph, or
  candidate-specific IRC endpoint identities. Those are explicit approval
  gaps, not values to infer from the literature geometry.
- The version-controlled coordinates, hashes, identities, expected results,
  and sequence gates are in `studies/wang_2024_bf3_ts/`. BF3 is a published
  computational comparison model here; it does not validate experimental BCF
  activity or the origin of enantioselectivity.

### JACS 2025, `10.1021/jacs.5c13835`

- Gaussian 16 Rev. A.03.
- Geometry optimization: PBE0-D3(BJ)/def2-SVP; frequencies for stationary
  points and one-imaginary-frequency TS classification.
- IRC used to connect TSs and minima.
- Gibbs energies at 283.15 K with Shermo 2.6 and Grimme harmonic/free-rotor
  entropy interpolation for low-frequency modes.
- Single points: PBE0-D3(BJ)/def2-TZVP with SMD(dichloromethane).
- Six stereodetermining TSs were reported. The lowest was interpreted as an
  organized borane/ligand structure stabilized by C-H...F contacts. The SI did
  not publish a systematic candidate-space ledger or ensemble selectivity.

## Reusable lessons

1. **The methods vary materially.** The verified papers use Gaussian 09 or 16,
   M06-2X, omega-B97XD, B3LYP-D3(BJ), or PBE0-D3(BJ), different basis stacks,
   GoodVibes or Shermo, and different temperatures. No one stack is a Wang-
   group default for a new reaction.
2. **Calculation purpose must be labeled.** Several DFT sections explain
   mechanism, regioselectivity, site selectivity, or catalyst coordination but
   not the experimental enantioselectivity.
3. **Experiments often carry the stereochemical argument.** Crystallography,
   nonlinear effects, matched/mismatched reactions and kinetic resolution are
   used where no new DFT ensemble is present. Preserve them as separate
   evidence rather than converting a cartoon into a computed TS claim.
4. **Useful recurring practices exist.** Two-level energy calculations,
   solvent treatment, reaction-temperature thermochemistry, low-frequency and
   standard-state handling, frequency classification, and IRC appear in the
   stronger mechanistic studies.
5. **Coverage is the main reusable gap.** The papers generally do not publish a
   machine-readable ledger of catalyst states, binding modes, conformers,
   exclusions, duplicates, failures and ensemble aggregation. The new Skill
   should add that provenance rather than merely reproduce a literature route.

## Sources

- Wang group publication list: <http://www.wangnankai.com/class/3>
- Nankai profile and selected publications:
  <https://skleoc.nankai.edu.cn/info/1753/5424.htm>
- Publisher DOI pages and public SI files for the DOI records above.
- Public 2019 spiro-bisborane article copy:
  <https://lac.dicp.ac.cn/53eAngewChemIntEd2019.pdf>
