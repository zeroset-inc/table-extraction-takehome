# Worked examples

All five run against `cases/above_below.evidence.json`:

```sh
validator/target/debug/validate \
  --evidence cases/above_below.evidence.json \
  --answer examples/accepted.proposal.json
```

| file | exit | what the validator says |
|---|---|---|
| `accepted.proposal.json` | 0 | `ACCEPTED` — prints the compiled layout with logical row spans |
| `unclassified-cell.proposal.json` | 1 | `layout proposal leaves occupied source cells unaccounted for` |
| `header-off-origin.proposal.json` | 1 | `primary header must start at the table origin` |
| `blank-records.proposal.json` | 1 | `layout data band contains empty source records; split around blank gaps` |
| `overlapping-tables.proposal.json` | 1 | `overlapping layout source ranges` |

Each rejection is one rule away from `accepted.proposal.json`. Diff them.

The annotation format (what you submit for scoring) is different from the layout
proposal format (what the validator compiles). `kit/build.py` writes both for
every case: `gold/<case>.json` is the annotation, `cases/<case>.reference-proposal.json`
is the same answer as a proposal. Reading one against the other is the fastest
way to understand both.
