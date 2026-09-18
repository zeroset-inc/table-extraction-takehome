"""Plumbing only: read a packet, write an empty answer. No interpretation.

    python3 kit/starter.py cases/above_below.packet.json answers/above_below.json

The answer it writes is deliberately empty, so the checker rejects it with
"Empty annotation." Replace `interpret()` with your own work. Everything else
here — A1 conversion, the response envelope, writing the file — is the part you
should not have to rewrite.
"""
import json
import pathlib
import sys


def address(point):
    row, column = point
    name, column = '', column + 1
    while column:
        column, rem = divmod(column - 1, 26)
        name = chr(65 + rem) + name
    return f'{name}{row + 1}'


def label(bounds):
    """Inclusive A1 range from half-open [row, column, row_end, column_end]."""
    return address((bounds[0], bounds[1])) + ':' + address((bounds[2] - 1, bounds[3] - 1))


def load(path):
    return json.loads(pathlib.Path(path).read_text(encoding='utf-8'))


def interpret(packet):
    """Return (tables, non_record_ranges, context_statements, uncertainties).

    `packet['source']['cells']` is a list of
        {"coordinate": [row, column], "cached_value": ..., "kind": "text"|"numeric"|"boolean",
         "formula_cache": null|"cached_unverified", "style": [bold, fill_class, borders, number_format]}
    and `packet['target_bounds']` is the half-open rectangle you must account for.

    Read POLICY.md before deciding what any of it means.
    """
    return [], [], [], []


def main(argv):
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    packet = load(argv[1])
    tables, non_records, statements, uncertainties = interpret(packet)
    answer = {
        'contract': 'table.annotation.v1',
        'packet_id': packet['packet_id'],
        'reviewer_id': 'candidate',
        'completion': 'complete',
        'human_name': 'your name',
        'independent_review': True,
        'prior_access_to_model_answers_or_gold': False,
        'evidence_sufficient': True,
        'tables': tables,
        'non_record_ranges': non_records,
        'context_statements': statements,
        'uncertainties': uncertainties,
        'reasoning': 'Explain your overall reading of this sheet.',
    }
    out = pathlib.Path(argv[2])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(answer, indent=2, ensure_ascii=False))
    print(f'wrote {out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
