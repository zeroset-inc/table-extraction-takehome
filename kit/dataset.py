"""The evaluation families: two hard geometry families under six transformations,
plus four applicability guards.

Every worksheet here is authored. No customer data, no model output, no expected
score enters fixture generation.

A *family* is one base worksheet. A *transformation* rewrites it while preserving
the correct answer:

    identity    the base, unchanged
    labels      every label renamed; the structure is untouched
    gap         two blank records opened inside the record band
    move        the whole thing relocated to a different origin
    transpose   rows and columns exchanged, so the record axis flips
    neighbor    a second, unrelated table added below

An extractor that reads structure generalizes across all six. One that has
learned the strings or the coordinates does not. That is the point of the split.
"""
import copy

import cases as fixtures


def runs(positions):
    out = []
    for i in sorted(set(positions)):
        if out and out[-1][1] == i:
            out[-1] = (out[-1][0], i + 1)
        else:
            out.append((i, i + 1))
    return out


def transform(f, kind):
    out = copy.deepcopy(f)
    if kind == 'labels':
        replacements = {'Service hours': 'Inspection hours', 'Staffing register': 'Inspection register',
                        'Site': 'Station', 'Area': 'District', 'North': 'Coastal', 'South': 'Inland',
                        'Account': 'Facility', 'Amount': 'Charge', 'Active': 'Verified',
                        'Device': 'Instrument', 'Online': 'Enabled', 'Units': 'Samples', 'Rate': 'Ratio',
                        'Birch': 'Aster', 'Elm': 'Juniper', 'Pine': 'Larch', 'Oak': 'Maple',
                        'Cedar': 'Willow', 'service credits': 'inspection charges',
                        'Service credit': 'Inspection charge'}

        def rename(x):
            if not isinstance(x, str):
                return x
            for a, b in sorted(replacements.items(), key=lambda kv: -len(kv[0])):
                x = x.replace(a, b)
            return x
        out['cells'] = {p: rename(v) for p, v in f['cells'].items()}
        return out
    if kind == 'neighbor':
        r = max(p[0] for p in f['cells']) + 6
        c = min(p[1] for p in f['cells']) + 1
        out['cells'][r, c] = 'Sensor observations'
        for j, v in enumerate(['Sensor', 'Reading', 'Verified']):
            out['cells'][r + 2, c + j] = v
        for i in range(4):
            for j, v in enumerate(['Sensor ' + str(i + 1), 37 + 11 * i, i % 2 == 0]):
                out['cells'][r + 3 + i, c + j] = v
        out['context'].append((len(out['tables']), fixtures.ref((r, c)), 'title', None))
        out['tables'].append(fixtures.table((r + 2, c, r + 7, c + 3), [r + 2], [(r + 3, r + 7)]))
        return out
    cut = f['tables'][0]['data'][0][0] + 2
    record_axis = 0 if f['tables'][0]['axis'] == 'records_by_row' else 1

    def point(p):
        r, c = p
        if kind == 'move':
            return r + 11, c + 7
        if kind == 'transpose':
            return c, r
        if kind == 'gap':
            q = list(p)
            q[record_axis] += 2 if p[record_axis] >= cut else 0
            return tuple(q)
        raise ValueError(kind)

    def rectangle(b):
        a, z = point(b[:2]), point((b[2] - 1, b[3] - 1))
        return min(a[0], z[0]), min(a[1], z[1]), max(a[0], z[0]) + 1, max(a[1], z[1]) + 1

    out['cells'] = {point(p): v for p, v in f['cells'].items()}
    out['tables'] = []
    for t in f['tables']:
        oldaxis = 0 if t['axis'] == 'records_by_row' else 1
        newaxis = 1 - oldaxis if kind == 'transpose' else oldaxis

        def index(i, t=t, oldaxis=oldaxis, newaxis=newaxis):
            p = list(t['bounds'][:2])
            p[oldaxis] = i
            return point(p)[newaxis]
        out['tables'].append(fixtures.table(
            rectangle(t['bounds']), [index(i) for i in t['headers']],
            runs(index(i) for a, b in t['data'] for i in range(a, b)),
            'records_by_row' if newaxis == 0 else 'records_by_column'))
    out['context'] = [(t, fixtures.ref(point(fixtures.coordinate(p))), role,
                       rectangle(target) if target else None)
                      for t, p, role, target in f.get('context', [])]
    out['unassigned'] = [fixtures.ref(point(fixtures.coordinate(p))) for p in f.get('unassigned', [])]
    return out


def register():
    cells = {(0, 1): 'Service reconciliation register', (12, 1): 'Amounts exclude emergency callouts.'}
    for c, v in enumerate(['Account', 'Amount', 'Active'], 1):
        cells[4, c] = v
    for r, name in enumerate(['Birch', 'Elm', 'Pine', 'Oak', 'Cedar'], 5):
        for c, v in enumerate([name, 17 + 13 * (r - 5), r % 2 == 0], 1):
            cells[r, c] = v
    return {'cells': cells, 'tables': [fixtures.table((4, 1, 10, 4), [4], [(5, 10)])],
            'context': [(0, 'B1', 'title', None), (0, 'B13', 'footnote', (4, 2, 10, 3))]}


def geometry_families():
    """sparse_record: a named record whose optional values are all blank.
       section_matrix: two header levels, a section divider and a reported total."""
    f = register()
    del f['cells'][7, 2]
    del f['cells'][7, 3]
    f['cells'][1, 1] = ('Every listed account is a record; blank Amount and Active entries '
                        'are unavailable.')
    f['context'].append((0, 'B2', 'explanation', None))

    matrix = {'cells': {(0, 1): 'Service volume report', (13, 1): 'Totals are reported source records.'},
              'tables': [fixtures.table((3, 1, 12, 5), [3, 5], [(7, 12)])],
              'context': [(0, 'B1', 'title', None), (0, 'B7', 'section', (7, 1, 12, 5)),
                          (0, 'B14', 'explanation', None)]}
    for c, v in enumerate(['Measure', '2025', '2025', '2025'], 1):
        matrix['cells'][3, c] = v
    for c, v in enumerate(['Measure', 'January', 'February', 'March'], 1):
        matrix['cells'][5, c] = v
    matrix['cells'][6, 1] = 'Regional service activity'
    for r, name in enumerate(['Completed', 'Pending', 'Cancelled', 'Other', 'Total'], 7):
        for c, v in enumerate([name, 13 * (r - 6), 17 * (r - 6), 19 * (r - 6)], 1):
            matrix['cells'][r, c] = v

    result = {}
    for family, base in [('sparse_record', f), ('section_matrix', matrix)]:
        for kind in ('identity', 'move', 'transpose', 'labels', 'gap', 'neighbor'):
            fixture = copy.deepcopy(base) if kind == 'identity' else transform(base, kind)
            if family == 'section_matrix' and kind == 'labels':
                replacements = {'Measure': 'Metric', 'January': 'April', 'February': 'May',
                                'March': 'June', 'Completed': 'Processed', 'Pending': 'Queued',
                                'Cancelled': 'Withdrawn', 'Other': 'Miscellaneous',
                                'Regional': 'District', 'Service volume': 'Inspection volume',
                                '2025': '2026'}

                def rename(value):
                    if isinstance(value, str):
                        for a, b in replacements.items():
                            value = value.replace(a, b)
                    return value
                fixture['cells'] = {p: rename(v) for p, v in fixture['cells'].items()}
            result[f'{family}_{kind}'] = {'fixture': fixture, 'family': family,
                                          'transformation': kind,
                                          'split': 'base' if kind == 'identity' else 'transformed'}
    return result


def applicability_guards():
    """One note per case, each with a different true scope."""
    definitions = {
        'mixed_fields': ('Amount excludes emergency callouts; Active means the account has been reconciled.',
                         [('definition', (4, 2, 10, 4))]),
        'mixed_general_field': ('All figures in this register are preliminary. Amount excludes emergency callouts.',
                                [('footnote', None)]),
        'mixed_record_field': ('For Elm, a manual adjustment is pending. Amount excludes emergency callouts.',
                               [('footnote', (6, 1, 7, 4)), ('footnote', (4, 2, 10, 3))]),
        'unspecified_scope': ('For this register, some entries require adjustments; the affected '
                              'accounts and fields are not identified.',
                              [('footnote', 'unresolved')]),
    }
    result = {}
    for case, (text, scopes) in definitions.items():
        f = register()
        f['cells'][12, 1] = text
        f['context'] = [(0, 'B1', 'title', None)] + [
            (0, 'B13', role, target if target != 'unresolved' else None) for role, target in scopes]
        f['unresolved_context'] = ['B13'] if scopes[0][1] == 'unresolved' else []
        result[case] = {'fixture': f, 'family': case, 'split': 'applicability_guard',
                        'transformation': None}
    return result


# Transformations the candidate does not see. Same families, so a structural
# extractor generalizes and a memorizing one does not.
HELD_OUT = {'move', 'transpose', 'neighbor'}


def all_cases(include_held_out=False):
    result = {**geometry_families(), **applicability_guards()}
    if not include_held_out:
        result = {k: v for k, v in result.items() if v['transformation'] not in HELD_OUT}
    return result
