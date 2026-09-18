"""Score one or more candidate answers against the authored gold.

    python3 kit/score.py answers/                 # a directory of <case>.json
    python3 kit/score.py answers/above_below.json  # a single answer

Three independent checks per case:

  format     the answer satisfies the annotation contract (kit/validate_response.py)
  geometry   the same tables, expressed as a layout proposal, survive the Rust
             validator — run separately with validator/target/debug/validate
  agreement  per decision type against gold/<case>.json, coordinate-normalized,
             so equivalent range splits are not counted as disagreement

Agreement is descriptive. It says where you and the authored answer differ, not
who is right. Read the disagreement details before trusting the totals.
"""
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import agreement          # noqa: E402
import validate_response  # noqa: E402

DECISIONS = ('record_role', 'header_membership', 'record_axis', 'non_record_role',
             'physical_occurrences', 'context_scope', 'context_role')


def load(path):
    return json.loads(pathlib.Path(path).read_text(encoding='utf-8'))


def locate(case):
    for cases, gold in ((ROOT / 'cases', ROOT / 'gold'),
                        (ROOT / 'heldout/cases', ROOT / 'heldout/gold')):
        if (cases / f'{case}.packet.json').exists() and (gold / f'{case}.json').exists():
            return cases / f'{case}.packet.json', gold / f'{case}.json'
    return None, None


def score_case(case, answer):
    packet_path, gold_path = locate(case)
    packet, gold = load(packet_path), load(gold_path)
    try:
        validate_response.validate_response(answer, packet, answer.get('reviewer_id'))
        fmt = 'ok'
    except Exception as error:           # noqa: BLE001 - reported, not raised
        return {'case': case, 'format': f'{error}', 'metrics': None}
    gold = dict(gold, reviewer_id=answer.get('reviewer_id'))
    comparison = agreement.compare(answer, gold, packet)
    return {'case': case, 'format': fmt, 'metrics': comparison['metrics'],
            'status': comparison['status']}


def main(argv):
    target = pathlib.Path(argv[1]) if len(argv) > 1 else ROOT / 'answers'
    paths = sorted(target.glob('*.json')) if target.is_dir() else [target]
    if not paths:
        print(f'no answers found in {target}', file=sys.stderr)
        return 2
    rows, totals = [], {name: [0, 0] for name in DECISIONS}
    for path in paths:
        answer = load(path)
        case = answer.get('packet_id') or path.stem
        if locate(case)[0] is None:
            print(f'{case}: no gold, skipped', file=sys.stderr)
            continue
        rows.append(score_case(case, answer))
    width = max(len(r['case']) for r in rows)
    print(f'{"case":<{width}}  format   ' + '  '.join(f'{n[:12]:>12}' for n in DECISIONS))
    for row in rows:
        if row['metrics'] is None:
            print(f'{row["case"]:<{width}}  INVALID  {row["format"][:70]}')
            continue
        flag = ' ' if row['status'] == 'provisional_agreement' else '*'
        cells = []
        for name in DECISIONS:
            m = row['metrics'][name]
            agreed, compared = m['agreed_units'], m['compared_units']
            totals[name][0] += agreed
            totals[name][1] += compared
            cells.append(f'{agreed:>5}/{compared:<6}' if compared else f'{"-":>12}')
        print(f'{row["case"]:<{width}}  ok{flag}      ' + '  '.join(cells))
    print(f'\n{"TOTAL":<{width}}           ' +
          '  '.join(f'{a:>5}/{c:<6}' if c else f'{"-":>12}' for a, c in
                    (totals[n] for n in DECISIONS)))
    disagreements = [(r['case'], name, d) for r in rows if r['metrics']
                     for name in DECISIONS for d in r['metrics'][name]['details']]
    if disagreements:
        print(f'\n{len(disagreements)} disagreement(s):')
        for case, name, detail in disagreements[:40]:
            print(f'  {case} · {name}: {json.dumps(detail)[:150]}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
