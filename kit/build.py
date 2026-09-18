"""Generate the case workbooks, reviewer packets, validator evidence and gold.

    python3 kit/build.py

Writes cases/<name>.xlsx, <name>.packet.json, <name>.view.html,
<name>.evidence.json and gold/<name>.json. Deterministic; safe to re-run.
"""
import html
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import cases as case_defs          # noqa: E402
import dataset                      # noqa: E402
import workbooks                    # noqa: E402
import xlsx                         # noqa: E402
import workbook                     # noqa: E402

# The authored scope intent for guards whose fixture target cannot express it.
SCOPE_OVERRIDE = {
    'policy_unresolved': {'B13': ('unresolved', 'unresolved', [])},
    'policy_unresolved_transposed': {'M2': ('unresolved', 'unresolved', [])},
}
# Fixture role names that the annotation vocabulary spells differently.
ROLE_MAP = {'period': 'title'}
NON_RECORD_ROLE = {'title': 'title', 'period': 'title', 'footnote': 'note', 'definition': 'note',
                   'unit': 'note', 'explanation': 'note', 'unresolved': 'unresolved'}


def bounding_box(points, merges=()):
    """The used range. A merge can reach past the last populated cell."""
    rows = [r for r, _ in points] + [m[0] for m in merges] + [m[2] - 1 for m in merges]
    columns = [c for _, c in points] + [m[1] for m in merges] + [m[3] - 1 for m in merges]
    return [min(rows), min(columns), max(rows) + 1, max(columns) + 1]


def occupied_rectangles(points):
    """Disjoint rectangles covering exactly the populated cells.

    Runs of adjacent columns become one rectangle per row, then identical runs in
    consecutive rows merge vertically. A dense 1,000-row table collapses to a
    single rectangle, which is what keeps large sheets inside the evidence bound.
    """
    by_row = {}
    for row in sorted({r for r, _ in points}):
        columns = sorted(c for r, c in points if r == row)
        runs, start, previous = [], columns[0], columns[0]
        for column in columns[1:] + [None]:
            if column != previous + 1:
                runs.append((start, previous + 1))
                if column is None:
                    break
                start = column
            previous = column if column is not None else previous
        by_row[row] = runs
    open_rectangles, closed = {}, []
    for row in sorted(by_row) + [None]:
        current = set(by_row.get(row, []))
        for run, top in list(open_rectangles.items()):
            if row is None or run not in current or row != open_rectangles[run][1] + 1:
                closed.append([top[0], run[0], top[1] + 1, run[1]])
                del open_rectangles[run]
        for run in sorted(current):
            if run in open_rectangles:
                open_rectangles[run] = (open_rectangles[run][0], row)
            else:
                open_rectangles[run] = (row, row)
    return sorted(closed)


def box(bounds):
    return {'start': {'row': bounds[0], 'column': bounds[1]},
            'end_exclusive': {'row': bounds[2], 'column': bounds[3]}}


def scope_of(table, target):
    """A target spanning the whole record axis is a field scope, and vice versa."""
    a, b, c, d = table['bounds']
    if table['axis'] == 'records_by_row':
        return 'fields' if (target[0] <= a and target[2] >= c) else 'records'
    return 'records' if (target[0] <= a and target[2] >= c) else 'fields'


PREVIEW_ROWS = 120


def view(case, packet, cells):
    bounds, target = packet['source']['bounds'], packet['target_bounds']
    limit = min(bounds[2], bounds[0] + PREVIEW_ROWS)
    truncated = limit < bounds[2]
    rows = range(bounds[0], limit)
    columns = range(bounds[1], bounds[3])
    head = ''.join(f'<th>{workbook.address((0, c))[:-1]}</th>' for c in columns)
    body = []
    for row in rows:
        tds = []
        for column in columns:
            cell = cells.get((row, column))
            outside = not (target[0] <= row < target[2] and target[1] <= column < target[3])
            klass = ' class="outside"' if outside else ''
            if not cell:
                tds.append(f'<td{klass}></td>')
                continue
            meta = [workbook.address((row, column)), cell['kind']]
            if cell['formula_cache']:
                meta.append('cache:' + cell['formula_cache'])
            tds.append(f'<td{klass}><div class="v">{html.escape(str(cell["cached_value"]))}</div>'
                       f'<div class="m">{" · ".join(meta)}</div></td>')
        body.append(f'<tr><th>{row + 1}</th>{"".join(tds)}</tr>')
    return f"""<!doctype html><html lang="en"><meta charset="utf-8"><title>{case}</title>
<style>body{{font:14px system-ui;margin:24px;color:#111}}table{{border-collapse:collapse}}
th{{font:12px monospace;background:#eee;padding:6px}}td{{vertical-align:top;min-width:88px;max-width:420px;
padding:6px;border:1px solid #ddd}}td.outside{{background:#f5f5f5}}.v{{white-space:pre-wrap;overflow-wrap:anywhere}}
.m{{font:10px monospace;color:#666;margin-top:5px}}p{{max-width:900px;line-height:1.5}}</style>
<h1>{case}</h1>
<p>Stored cached values only; formulas are never evaluated or displayed. Bounds
{workbook.range_label(bounds)}; extraction target {workbook.range_label(target)}. Gray cells lie
outside the target. This is a reconstruction of the admitted observations, not a screenshot of Excel.</p>
<table><thead><tr><th></th>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>
{f'<p><b>Preview truncated</b> at row {limit} of {bounds[2]}. The packet JSON holds every cell.</p>' if truncated else ''}</html>"""


def gold(case, fixture, cells):
    roles = fixture.get('roles', {})
    tables, statements, non_records = [], [], []
    covered = set()
    for index, table in enumerate(fixture['tables']):
        a, b, c, d = table['bounds']
        axis = 0 if table['axis'] == 'records_by_row' else 1
        full = (b, d) if axis == 0 else (a, c)
        def band(lo, hi):
            return [lo, full[0], hi, full[1]] if axis == 0 else [full[0], lo, full[1], hi]
        tables.append({
            'table_id': f'T{index + 1}',
            'source_range': workbook.range_label(table['bounds']),
            'record_axis': 'rows' if axis == 0 else 'columns',
            'primary_header_ranges': [workbook.range_label(band(h, h + 1)) for h in table['headers']],
            'record_ranges': [workbook.range_label(band(lo, hi)) for lo, hi in table['data']],
            'repeated_header_ranges': [],
            'reason': 'Authored layout: header levels and record bands as generated.',
        })
        for point in cells:
            if a <= point[0] < c and b <= point[1] < d:
                position = point[axis]
                if position in table['headers'] or any(lo <= position < hi for lo, hi in table['data']):
                    covered.add(point)
    for table_index, ref, role, target in fixture.get('context', []):
        point = workbook.coordinate(ref)
        table = fixture['tables'][table_index]
        state, scope, ranges = 'resolved', 'table', []
        if target:
            scope, ranges = scope_of(table, target), [workbook.range_label(target)]
        override = SCOPE_OVERRIDE.get(case, {}).get(ref)
        if override:
            state, scope, ranges = override
        statements.append({
            'evidence_cell': ref,
            'exact_excerpt': str(cells[point]['cached_value']),
            'occurrence_index': 0,
            'retaining_tables': [f'T{table_index + 1}'],
            'role': ROLE_MAP.get(role, role),
            'applicability': {'state': state, 'scope': scope, 'source_ranges': ranges},
            'reason': 'Authored applicability for this statement.',
        })
        if point not in covered:
            non_records.append({'source_range': ref,
                                'role': roles.get(ref, NON_RECORD_ROLE.get(role, 'note')),
                                'reason': 'Retained statement; not a header or record.'})
            covered.add(point)
    for ref in fixture.get('unassigned', []):
        point = workbook.coordinate(ref)
        statements.append({
            'evidence_cell': ref,
            'exact_excerpt': str(cells[point]['cached_value']),
            'occurrence_index': 0,
            'retaining_tables': [],
            'role': 'unresolved',
            'applicability': {'state': 'unresolved', 'scope': 'unresolved', 'source_ranges': []},
            'reason': 'Table association is unsupported; the statement is retained unattached.',
        })
        non_records.append({'source_range': ref, 'role': 'unresolved',
                            'reason': 'Copied source material with no supported table membership.'})
        covered.add(point)
    for point in sorted(cells.keys() - covered):
        ref = workbook.address(point)
        non_records.append({'source_range': ref, 'role': roles.get(ref, 'other'),
                            'reason': 'Populated cell outside every table and statement.'})
    return {'contract': 'table.annotation.v1', 'packet_id': case, 'reviewer_id': 'gold',
            'completion': 'complete', 'human_name': 'authored gold',
            'independent_review': True, 'prior_access_to_model_answers_or_gold': True,
            'evidence_sufficient': True, 'tables': tables, 'non_record_ranges': non_records,
            'context_statements': statements, 'uncertainties': [],
            'reasoning': 'Generated from the authored fixture definition.'}


def proposal(fixture, cells):
    """The same answer in the layout-proposal format the Rust validator compiles."""
    selections, covered = [], set()
    for index, table in enumerate(fixture['tables']):
        a, b, c, d = table['bounds']
        axis = 0 if table['axis'] == 'records_by_row' else 1
        selections.append({
            'region_id': f't{index}',
            'orientation': table['axis'],
            'source_range': box(table['bounds']),
            'header_bands': [{'start': h, 'end_exclusive': h + 1} for h in table['headers']],
            'data_bands': [{'start': lo, 'end_exclusive': hi} for lo, hi in table['data']],
        })
        for point in cells:
            if a <= point[0] < c and b <= point[1] < d:
                position = point[axis]
                if position in table['headers'] or any(lo <= position < hi for lo, hi in table['data']):
                    covered.add(point)
    unassigned = {workbook.coordinate(r) for r in fixture.get('unassigned', [])}
    excluded = [{'source_range': box([p[0], p[1], p[0] + 1, p[1] + 1]),
                 'disposition': 'unresolved' if p in unassigned else 'non_table'}
                for p in sorted(cells.keys() - covered)]
    return {'contract': 'table.layout-proposal.v1', 'selections': selections,
            'excluded_ranges': excluded}


def collect(include_held_out):
    """Format guards teach the annotation format; families test generalization."""
    result = {case: {'fixture': f, 'family': case, 'split': 'format_guard',
                     'transformation': None}
              for case, f in case_defs.all_cases().items()}
    result.update(dataset.all_cases(include_held_out=include_held_out))
    return result


def build(entries, case_dir, gold_dir):
    case_dir.mkdir(parents=True, exist_ok=True)
    gold_dir.mkdir(parents=True, exist_ok=True)
    built = []
    for case, entry in sorted(entries.items()):
        fixture = entry['fixture']
        path = case_dir / f'{case}.xlsx'
        case_defs.write(path, fixture['cells'],
                        hidden_empty=fixture.get('hidden_empty', False),
                        stale=fixture.get('stale', False))
        cells, merges = workbook.worksheet(path, 'Observations'), []
        if isinstance(cells, tuple):
            cells, merges = cells
        bounds = bounding_box(cells)
        packet = {'contract': 'table.packet.v1', 'packet_id': case,
                  'target_bounds': bounds,
                  'source': {'bounds': bounds, 'date_system': '1900', 'merges': merges,
                             'cells': [{'coordinate': list(p), **cells[p]} for p in sorted(cells)]}}
        packet['family'] = entry['family']
        packet['transformation'] = entry['transformation']
        packet['split'] = entry['split']
        (case_dir / f'{case}.packet.json').write_text(json.dumps(packet, indent=1))
        (case_dir / f'{case}.view.html').write_text(view(case, packet, cells))
        evidence = {'window': box(bounds), 'occupied_ranges': [box(r) for r in occupied_rectangles(cells)],
                    'merged_ranges': [], 'explicit_table_ranges': []}
        (case_dir / f'{case}.evidence.json').write_text(json.dumps(evidence, indent=1))
        (case_dir / f'{case}.reference-proposal.json').write_text(
            json.dumps(proposal(fixture, cells), indent=1))
        (gold_dir / f'{case}.json').write_text(json.dumps(gold(case, fixture, cells), indent=1))
        built.append((case, entry['split'], len(cells)))
    return built


def build_workbook(spec, case_dir, gold_dir):
    """One packet per worksheet, including the sheets that hold no table."""
    name, sheets, fixtures = workbooks.build(spec)
    case_dir.mkdir(parents=True, exist_ok=True)
    gold_dir.mkdir(parents=True, exist_ok=True)
    path = case_dir / f'{name}.xlsx'
    xlsx.write(path, sheets)
    built = []
    for sheet in sheets:
        cells, merges = workbook.worksheet(path, sheet.name)
        if not cells:
            continue
        merges = [m for m in merges if any(m[0] <= r < m[2] and m[1] <= c < m[3] for r, c in cells)]
        case = f'{name}__' + sheet.name.lower().replace(' ', '_').replace('&', 'and')
        fixture = fixtures[sheet.name]
        bounds = bounding_box(cells, merges)
        packet = {'contract': 'table.packet.v1', 'packet_id': case, 'target_bounds': bounds,
                  'workbook': f'{name}.xlsx', 'sheet': sheet.name,
                  'sheet_visibility': sheet.visibility, 'family': name,
                  'transformation': None, 'split': 'workbook',
                  'source': {'bounds': bounds, 'date_system': '1900', 'merges': merges,
                             'cells': [{'coordinate': list(p), **cells[p]} for p in sorted(cells)]}}
        (case_dir / f'{case}.packet.json').write_text(json.dumps(packet, indent=1))
        (case_dir / f'{case}.view.html').write_text(view(case, packet, cells))
        evidence = {'window': box(bounds), 'occupied_ranges': [box(r) for r in occupied_rectangles(cells)],
                    'merged_ranges': [box(m) for m in merges], 'explicit_table_ranges': []}
        (case_dir / f'{case}.evidence.json').write_text(json.dumps(evidence, indent=1))
        (case_dir / f'{case}.reference-proposal.json').write_text(
            json.dumps(proposal(fixture, cells), indent=1))
        (gold_dir / f'{case}.json').write_text(json.dumps(gold(case, fixture, cells), indent=1))
        built.append((case, 'workbook', len(cells)))
    return built


def main():
    held_out = '--held-out' in sys.argv
    case_dir = ROOT / ('heldout/cases' if held_out else 'cases')
    gold_dir = ROOT / ('heldout/gold' if held_out else 'gold')
    entries = collect(include_held_out=True) if held_out else collect(include_held_out=False)
    if held_out:
        entries = {k: v for k, v in entries.items()
                   if v['transformation'] in dataset.HELD_OUT}
    built = build(entries, case_dir, gold_dir)
    spec = workbooks.held_out_operations() if held_out else workbooks.OPERATIONS
    built += build_workbook(spec, case_dir, gold_dir)
    width = max(len(c) for c, _, _ in built)
    for case, split, cell_count in built:
        print(f'{case:<{width}}  {split:<19} {cell_count:>4} cells')
    print(f'\n{len(built)} cases written to {case_dir.relative_to(ROOT)}/ and '
          f'{gold_dir.relative_to(ROOT)}/')


if __name__ == '__main__':
    main()
