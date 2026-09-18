# Worksheet interpretation policy

Identify the source's physical tables, their headers and records, and what nearby
source statements qualify. Keep separate occurrences separate even when they
share field names. Preserve source scalar values and original coordinates. Do
not repair formulas or invent a business interpretation.

For registers, each identified entity or observation is a record, including when
records run across columns. Position labels such as A1 name source coordinates;
they do not decide which cells are field names. A legitimate record can have
blank optional fields.

For reporting matrices, preserve supported parent/leaf header levels, section
structure and named report lines. Examine both axes. If both representations are
equally faithful and neither has stronger field/record evidence, preserve physical
source rows; record the alternative as acceptable rather than pretending the
source selects a unique axis. Do not enforce the original orientation of an
unseen pre-transformation source.

A parent label naming a subset of fields belongs in those fields' header
hierarchy, including sparse or unmerged labels. A whole-table title or general
statement remains context. Headers can have noncontiguous levels. The supported
physical contract permits at most eight primary levels within a sixteen-position
span. Label an interpretation outside those limits explicitly.

A section divider names a group of following records; a reported total remains
a report line when the source represents it that way. Sparsity, merged cells,
formatting or a text label alone do not settle this distinction. Preserve a named
entity with unavailable optional values as a record. Use uncertainty when source
evidence cannot distinguish the interpretations.

Context retention and applicability are separate. A field-specific note stays in
the retaining table's description while qualifying only that field. Titles,
general reporting periods and statements about the report as a whole apply to
the whole table. Record-specific statements qualify those records. Mentioning a
record does not automatically restrict a statement to it.

Split a mixed-purpose excerpt into its exact source statements when the clauses
have different scopes. Quote each statement exactly and record its evidence cell;
code will derive UTF-8 offsets. Do not rewrite source text. Scope may be a table,
fields, records, or their intersection. If association with a table is supported
but its fields/records are unclear, retain the statement with unresolved
applicability. If even the table association is unsupported, leave it unattached.
Role labels such as title, unit, definition, footnote, section or explanation do
not determine scope. Role uncertainty and scope uncertainty are separate.

Primary headers already define the schema. Do not duplicate them as context
unless they supply additional information. A title retained as context cannot
replace a missing schema header.

Physical classification and context attachment are independent annotations.
Account for each populated target cell as a header, record or non-record, or
explicitly record uncertainty about its physical role. This includes target cells
outside all table rectangles. A retained title or note needs both its non-record
classification and its context attachment. Context annotations alone do not
classify cells physically; header cells may also supply additional context.

When more than one interpretation is supported, keep a preferred answer if you
have one and record the supported alternatives under `uncertainties`. Do not hide
an acknowledged alternative only in a reason field. Multiple supported answers
do not necessarily mean evidence is missing: use `evidence_sufficient: false`
only when additional evidence is needed. Record actual uncertainty, not every
conceivable alternative or a blanket choice to suppress all alternatives.

Assess only the outlined extraction target. Surrounding cells are evidence, not
additional extraction targets. A target edge need not be an actual table edge.
The displayed values are stored workbook caches, not freshly calculated results.
The view reconstructs selected static formatting and merges; it does not assert
pixel equivalence to Excel. Report when omitted presentation or more source
context would be necessary to decide.
