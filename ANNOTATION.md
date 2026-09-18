# Independent human worksheet review

Open `index.html`, read `POLICY.md`, then review the packets in the listed order.
Each populated cell shows its Excel A1 address, and the view lists A1 bounds.
Use these addresses in your answers: `B4:E12` includes both endpoints. The
expandable source JSON instead uses zero-based coordinates and exclusive ends;
these describe the same cells. Annotate only the extraction target. Gray cells
outside it provide context.

Edit the corresponding JSON under `responses/`. Do this independently, without
viewing the other review, historical annotations or model answers. Supply your
name and the two independence declarations. If you already saw relevant answers,
declare that access instead of claiming blindness. Leave `completion` as
`pending` until the packet is finished; then set it to `complete`.

Before returning a response, run the included offline checker with Python 3:

```sh
python3 -B validate_response.py --validate responses/YOUR-PACKET-ID.json
```

It checks your response against this bundle's packet, including ranges, quoted
text and allowed choices. Exit 0 means a complete response passes those checks;
it does not judge your interpretation or certify that every cell is classified.
Exit 1 identifies an invalid response.
Exit 2 means the response is still pending and has not been fully checked.
The checker uses no network or curator files and does not edit your answers.

For each physical table, add an entry under `tables`:

```json
{
  "table_id": "T1",
  "source_range": "B3:D7",
  "record_axis": "rows",
  "primary_header_ranges": ["B3:D3"],
  "record_ranges": ["B4:D7"],
  "repeated_header_ranges": [],
  "reason": "Explain what the labels and records represent using source evidence."
}
```

The example is a format illustration, not an answer for a packet. Use `columns`
for records across columns. Name separate physical occurrences T1, T2, etc.
List all supported parent/leaf header levels and data intervals. Leave blank
source cells blank. For section dividers, titles or other excluded material, add
`{"source_range":"A9:D9","role":"section","reason":"..."}` under
`non_record_ranges`. Allowed roles are `section`, `title`, `note`, `other`,
and `unresolved`. Do not classify a genuine sparse record as a divider.

Account for every populated cell inside the extraction target, including cells
outside your table rectangles. Use header/record ranges, `non_record_ranges`, or
an explicit `record_role` uncertainty. A context entry does not supply a physical
classification. For example, if table T1 occupies `B3:D7` and a retained title
`B1` lies inside the target, annotate **both** independent decisions:

```json
{
  "non_record_ranges": [
    {"source_range": "B1", "role": "title", "reason": "Names the table; it is not a header or record."}
  ],
  "context_statements": [
    {
      "evidence_cell": "B1",
      "exact_excerpt": "Annual service register",
      "occurrence_index": 0,
      "retaining_tables": ["T1"],
      "role": "title",
      "applicability": {"state": "resolved", "scope": "table", "source_ranges": []},
      "reason": "The title names this table."
    }
  ]
}
```

This is a separate format illustration; quote the actual source text in your
packet. An unattached note still needs a physical classification. Header cells
can also carry additional context without becoming non-records. Blank padding
around a sparse header does not change populated-cell membership: ranges that
cover the same populated header cells compare equally. A header label with blank
peer cells can be represented in the existing header ranges; do not invent values.

For each contextual statement, add an entry under `context_statements`:

```json
{
  "evidence_cell": "A10",
  "exact_excerpt": "Copy the relevant statement exactly from its source cell.",
  "occurrence_index": 0,
  "retaining_tables": ["T1"],
  "role": "footnote",
  "applicability": {
    "state": "resolved",
    "scope": "fields",
    "source_ranges": ["B3:B7"]
  },
  "reason": "Explain why this statement qualifies these fields or records."
}
```

Split statements with different purposes into separate entries. Preserve exact
punctuation and spaces; `occurrence_index` selects a repeated identical excerpt
in the same cell, starting at zero. Code derives byte offsets, so you do not need
to count them. Allowed applicability scopes are `table`, `fields`, `records`,
`field_records`, and `unresolved`. Whole-table scope uses an empty range list;
unresolved scope uses `state: "unresolved"` and an empty range list. If table
association itself is unsupported, use an empty retaining-table list. Roles are
`title`, `header`, `unit`, `definition`, `footnote`, `section`, `explanation`,
`status_key`, `other`, or `unresolved`.

For a supported alternative or insufficient evidence, add an `uncertainties`
entry with `source_range`, `decision` (`record_role`, `header_membership`,
`record_axis`, or `context_scope`), `supported_options`, and `reason`. Do not
force a single answer. Mark `evidence_sufficient` false when more source evidence
is needed and state precisely what is missing. The packet-level `reasoning`
field can capture your overall judgment or concerns with the policy.

Keep your preferred interpretation in the ordinary fields when one is supported,
and list any other supported interpretation in `uncertainties`. A reason saying
another answer is acceptable does not replace this structured entry. For context
scope, anchor `source_range` at the statement's **evidence cell**, not the cells
it qualifies. For the A10 statement above, a supported alternative could be:

```json
{
  "source_range": "A10",
  "decision": "context_scope",
  "supported_options": ["Qualifies field B in T1", "Qualifies T1 as a whole"],
  "reason": "Explain the source evidence supporting each reading."
}
```

This is an illustration, not an instruction to mark that statement uncertain.
Multiple supported readings can coexist with `evidence_sufficient: true`; set it
false only when you need more source evidence. The comparison uses structured
uncertainties and preserves your reasons for adjudication; it does not infer
alternatives from prose. You need not mark every difficult decision uncertain.

Keep model names, confidence scores and historical outcomes out of this review.
Do not discuss interpretations until both completed submissions have been locked
by the coordinator. Your answers will be compared by decision type; disagreement
will be adjudicated without rewriting the historical benchmark scores.

Blinding hides prior answers, annotations, scores and selection labels. Exact
worksheet labels and values may still let you recognize a source. Record source
familiarity in `reasoning`; recognizing a workbook differs from having seen its
prior answers. Declare prior answer access truthfully using the existing field.
