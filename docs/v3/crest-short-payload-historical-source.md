# Auto-G16 CREST short-entry historical-source compatibility

This bounded clarification accompanies SP01/SP05/SP07 in
[the frozen short-entry contract](crest-short-payload-contract.md). It does not
change that document's qualification-bound bytes or scientific authority.

The new submit payload changes the fixed production bridge. The existing xTB
receipt-only source reader previously required the current bridge bytes to equal
the historical locator. That would invalidate the authentic 693 source solely
because this new candidate changes delivery, despite its original stores,
receipt, capture and Result remaining exact.

Retain the predecessor bridge source bytes as an explicit private generation:
SHA256 `b80962b8f0425f32206f228ee3e65b76749b8d447e826427dca8241d541166fb`,
15090 bytes. Derive the new fixed bridge only by its closed submit-key extension.
The receipt-only source reader accepts only either of these source-owned exact
byte identities. It returns the locator's original identity and retains all
original snapshot, store path/inode/hash, journal, receipt, capture and Result
checks. No caller-selected source, arbitrary allowlist, edited locator, new
historical timestamp or live installation is introduced. The retained generation
is never selected to run a new Attempt.

Validation must build a genuinely old-generation inert source before switching
to the new candidate and show read-only proof reconstruction without a live
installation, remote effect, store mutation or resubmission. Wrong digests and
store replacements remain refusals. The actual 693 locator and databases stay
unchanged; no new xTB computation is required.
