# Online research and evidence

## Source hierarchy

Use the strongest available representation, favoring:

1. A user-supplied structure file, DOI-linked supporting information, patent example, or official registry record that clearly identifies the exact compound.
2. Authoritative machine-readable chemical databases and APIs, such as PubChem records with CID, canonical/isomeric SMILES, InChI, InChIKey, charge, and formula.
3. Curated scholarly databases or the original paper/patent containing an unambiguous structure and compound number.
4. Manufacturer records with CAS/registry number and a structure representation.
5. Aggregators, search snippets, catalogs, and image search only as discovery leads.

Do not assume that matching names mean matching salt, solvate, tautomer, protonation state, or stereoisomer.

## Research procedure

1. Search the exact quoted name plus stable identifiers (CAS, DOI, patent/example, catalog number) when present.
2. Open the underlying record; never use a search-result snippet as evidence.
3. Capture the record title, stable identifier, exact form, formula, formal charge, stereochemical descriptor, and machine-readable structure.
4. Canonicalize each candidate locally with RDKit. Compare canonical isomeric SMILES, InChIKey when available, formula, charge, and fragment count.
5. Resolve disagreements using the strongest source and the user's context. If disagreement remains chemically material, pause for confirmation.
6. Research depiction convention separately from chemical identity for familiar structures. Identity sources prove what the molecule is; representative literature depictions establish how readers expect to see it.

## Evidence ledger

Record at least:

| Field | Meaning |
|---|---|
| requested_name | User wording |
| resolved_name | Exact selected identity/form |
| source_url | Direct record or document URL |
| source_id | CID, CAS, DOI, patent/example, catalog ID, etc. |
| source_role | primary, authoritative database, secondary, or visual lead |
| source_structure | Retrieved SMILES/InChI or `visual-only` |
| agreement | What independent evidence agrees on |
| unresolved | Any remaining ambiguity |
| confidence | verified, supported, provisional, or unresolved |
| depiction_reference | Representative literature URL/DOI or reviewed template |
| literature_consensus | Modal scaffold orientation and viewing convention |

Use `verified` only when exact form and stereochemistry are supported by strong agreeing evidence and local validation. Use `supported` for a well-supported unambiguous structure with a minor representation limitation. Use `provisional` for a single-source or partly reconstructed result. Do not finalize `unresolved` structures.

## Name-resolution cautions

- Expand abbreviations only from context or a source; ligand and catalyst abbreviations are often non-unique.
- Check whether a database synonym points to the parent, free base/acid, salt, hydrate, solvate, isotope, or mixture.
- For natural products and drugs, require stereochemical agreement; a connectivity-only canonical SMILES is insufficient.
- For named reactions or catalysts, do not confuse a class name with one specific compound.
- Record access date in the final manifest when web evidence is used.
