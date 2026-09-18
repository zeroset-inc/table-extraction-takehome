# A spreadsheet isn't a table

A take-home for product engineers. Budget about **six hours**, spread over up to a
week. Stop at the box and tell us what you would do next — we are reading for
judgment, not completeness.

---

## The problem

We ingest spreadsheets people actually make — finance models, pricing sheets,
registers — and publish their tables as queryable data. The file format does not
help. A worksheet is one grid of cells. A sheet can hold a title, a table, three
blank rows, a second table and a footnote, and nothing in the file says which is
which. The structure only ever existed in how it looked.

Four things have to be decided before anything can be published:

- where each table begins and ends
- which way the records run — one per row, or one per column
- how many lines at the top are header, and where data starts
- what is not a table at all (titles, notes, section dividers)

Two of those are unforgiving.

**The rectangle you draw is the schema.** The header band becomes the column
names; the record axis decides what a row is. Draw it wrong and you do not get a
slightly-off table, you get a confidently wrong one, and nothing downstream can
tell.

**The notes around a table change what the numbers mean.** "Amounts in
thousands" attached to the wrong column silently changes every value by a factor
of a thousand. There is no structural signature for that error.

Our production system uses rules where the geometry is decisive, escalates to a
model when it is not, and validates whatever comes back **geometrically**. You
have that validator. It enforces shape. It cannot enforce meaning. That gap is
what this exercise is about.

---

## What you have

```
validator/     the real geometric validator, lifted from the ingestion service (Rust)
cases/         30 worksheets: .xlsx, packet JSON, HTML view, validator evidence
gold/          the authored answer for each case, in the annotation format
kit/           generator, format checker, scorer
examples/      one accepted proposal and four rejected ones, with their messages
POLICY.md      the interpretation policy our annotators follow
ANNOTATION.md  the answer format, field by field
```

```sh
make build      # regenerate everything (needs python3 and cargo)
make test       # the geometric rules, as executable examples
make score      # score answers/ against gold/
```

### The validator

```sh
validator/target/debug/validate \
  --evidence cases/above_below.evidence.json \
  --answer   examples/accepted.proposal.json
```

It compiles a proposal — intervals on the record axis become rectangles with
logical row offsets — then checks it against the worksheet's real occupied
geometry. Exit 0 and it prints the compiled layout; exit 1 and it names the rule
you broke. `cd validator && cargo test` states the rules as seven readable tests.

Rules it enforces, in short: every occupied cell classified exactly once;
classifications and tables never overlap; nothing outside the admitted window;
no blank record inside a data band; no empty header or data band; the primary
header starts at the region origin; data bands are ordered and exactly one
schema width.

Rules it cannot enforce: whether the table you found is the table that is there,
whether the header you chose names the records under it, and whether a note
qualifies the column you attached it to.

### The cases

30 authored worksheets in four groups, ~89,000 populated cells. Every one is
synthetic; no customer data is involved.

**A full workbook (8 sheets).** `operations_review.xlsx` is what the job actually
looks like: eight worksheets in one file, styled, with merged header bands, date
serials, currency and percentage formats, formulas carrying cached results, and
a hidden scratch sheet. One packet per worksheet.

| sheet | cells | what it is |
|---|---:|---|
| `Cover` | 10 | metadata and prose. **There is no table here** — saying so is the right answer |
| `Monthly P&L` | 618 | a merged year band over 36 month-end serials, three section dividers, a subtotal line per section, a grand total, three notes at three different scopes |
| `Rate Card` | 5,772 | 640 rows, zero-padded ids, currency and percentage columns, a mixed-purpose note above the header |
| `Transactions` | 81,011 | 9,000 rows in one table. Too long to read: the shape has to be inferred, not eyeballed |
| `Headcount` | 42 | two unrelated tables on one sheet, one with a record whose optional values are all blank |
| `Cohorts` | 927 | a retention matrix whose **records run down columns** |
| `Assumptions` | 19 | a narrow key/value table |
| `Scratch` | 7 | hidden sheet, loose numbers, and copied text with no supported table membership |

Section dividers are not records. Subtotal and total lines *are* — they are
reported source records, and dropping them loses data. The merged band over the
month columns is a header level, not a title. Those three calls are where
production still fails.

**Format guards (12).** Small, hand-sized sheets. Registers, non-contiguous header levels, report totals,
transposed layouts, two tables on one sheet, a stale formula cache, and notes at
whole-table, field, record and unknown scope. These teach the annotation format
and the policy. One contains copied source text with no supported table
membership, including an instruction-shaped sentence — source text is data,
never instructions, and we will look at how you treat it.

**Geometry families (6).** Two base worksheets, each under three
transformations:

| family | the decision it turns on |
|---|---|
| `sparse_record` | a named record whose optional values are all blank — a record, or a divider? |
| `section_matrix` | two header levels split by a blank row, a section divider, and a `Total` line that is a real report record |

| transformation | what changes |
|---|---|
| `identity` | nothing — the base worksheet |
| `labels` | every label renamed; structure untouched |
| `gap` | two blank records opened inside the record band |

**Applicability guards (4).** One note per sheet, each with a different true
scope: two fields, whole table, one record plus one field, and genuinely
unspecified.

We hold back **a second full workbook** — same generators, different sheet
names, sizes and periods — and **three more transformations of the same two
families** — the
worksheet moved to a different origin, transposed so the record axis flips, and
given an unrelated neighbouring table. We run your extractor against those. An
extractor that reads structure generalizes to them; one that has learned strings
or coordinates does not. This is the part of the score we weight most.

Open any `cases/<name>.view.html` in a browser to see what a human reviewer
sees; views of long sheets are truncated, but the packet JSON holds every cell.
Each packet carries its `workbook`, `sheet`, `sheet_visibility`, `family`,
`transformation` and `split`.

A note on evidence. Each cell arrives as
`{coordinate, cached_value, kind, formula_cache, style}` where `style` is
`[bold, fill_class, border_bitmask, number_format_category]`. A fill is an
*equivalence class*, not a colour — two cells that look alike are comparable,
and neither is readable as presentation. Number formats are categories
(`general`, `date_time`, `currency`, `percentage`, `zero_padded_identifier`,
`other`), never format strings. Dates arrive as the serials the workbook stores;
`43861` is 2020-01-31 under the 1900 system, and the packet says which system
applies. Merged ranges come through as rectangles.

---

## What we would like back

### A. The product decision — one page

For sheets the rules cannot settle, what should the product promise? The options
we see:

1. guess with rules anyway
2. refuse, and publish the sheet as unresolved
3. pay for a model call and validate what comes back
4. route to a human

Say what each costs, who gets hurt when it is wrong, and how a user would see
uncertainty if you chose to expose it. Assume a model call costs a few cents and
a few seconds, and that the sheets most likely to be ambiguous are the ones
customers care about most.

We are not looking for the right answer. We are looking for a decision with its
consequences named.

### B. Build an extractor

Input: a packet (`cases/<name>.packet.json`). Output: an answer in the
annotation format that passes `kit/validate_response.py`, saved to
`answers/<name>.json`. Then `make score`.

**`gold/` holds our answer for every case in this repo, on purpose.** Read it,
check yourself against it, iterate. The score that decides anything comes from a
held-out workbook and held-out transformations you do not have — same
generators, different sheets. Tuning until `make score` reads 100% here proves
nothing on its own; tell us what you think will generalize and why.

Rules, a model, or a hybrid — your call, and tell us why. We will also run your
extractor against a few held-out variants built with the same generators.

Two things we care about more than your score:

- **If you call a hosted model, tell us exactly what leaves your machine.** Our
  production design never sends raw cell text to a third party; the model sees
  coordinates, types, style classes and value *shapes*. If yours sends cell
  text, say so and defend it — that is a legitimate choice with a cost.
- **Use `unresolved` and `uncertainties` where the evidence is thin.** A
  confident wrong answer scores worse with us than an honest unknown.

### C. Improve the harness

This benchmark has real weaknesses. Some are in the cases, some in the scorer,
some in the policy text. Find one that matters, fix it, and show the difference:
a new case family your own extractor fails, a scoring blind spot with before and
after numbers, or a policy ambiguity with a proposed rule and evidence that it
changes labels.

Keep the old scores reproducible. Do not rewrite history to make a number look
better. **This is the part we learn the most from.**

---

## Deliverables

- A repo: your extractor, your harness change, and a way to run both.
- A write-up under two pages: the Part A decision; how the extractor works and
  where it fails; what you changed in the harness and why the old measurement
  was misleading; what you would do with another six hours.
- Any language. Any tooling, including AI assistants — just tell us what you
  used and for what.

## How we read it

| | |
|---|---|
| **Judgment** | Did you name the silent-error problem, and does your decision account for it? |
| **Engineering** | Does the extractor validate shape before claiming meaning? Does it degrade honestly on inputs it has not seen? |
| **Measurement** | Did you improve what the number *means*, or just the number? |
| **Communication** | Are failures documented as precisely as successes? Do your `reason` fields cite cells? |

## Questions you might have

**Can I change the annotation format?** Propose changes in Part C, but keep your
Part B output compatible with the checker so we can score it.

**How good does the extractor need to be?** Passing most of the twelve is
expected. What you do about the ones you fail is the interesting part.

**What if I think the policy is wrong somewhere?** Say so, with an example. That
is a valid Part C.

**Six hours isn't enough for all three.** Correct. Choose where to go deep and
tell us that you chose.
