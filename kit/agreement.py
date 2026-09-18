"""Coordinate-normalized human agreement; no gold comparison or label selection."""
from collections import defaultdict

from validate_response import cell_coordinate, exact_slice, source_range


def inside(bounds, point):
    return bounds[0] <= point[0] < bounds[2] and bounds[1] <= point[1] < bounds[3]


def points(area):
    return {(r, c) for r in range(area[0], area[2]) for c in range(area[1], area[3])}


def ranges(values, target):
    return set().union(*(points(source_range(v, target)) for v in values)) if values else set()


def normalized(answer, packet):
    target = packet['target_bounds']
    roles = defaultdict(set); headers = defaultdict(set); axes = defaultdict(set)
    excluded = defaultdict(set); tables = {}
    for table in answer['tables']:
        area = source_range(table['source_range'], target)
        tables[table['table_id']] = tuple(area)
        for key, label in [('primary_header_ranges', 'primary'), ('repeated_header_ranges', 'repeated')]:
            for p in ranges(table[key], area):
                roles[p].add('header'); headers[p].add(label)
        for p in ranges(table['record_ranges'], area):
            roles[p].add('record'); axes[p].add(table['record_axis'])
    for item in answer['non_record_ranges']:
        for p in points(source_range(item['source_range'], target)):
            roles[p].add('unresolved' if item['role'] == 'unresolved' else 'non_record')
            excluded[p].add(item['role'])
    uncertain = defaultdict(set)
    for item in answer['uncertainties']:
        uncertain[item['decision']].update(points(source_range(item['source_range'], target)))
    cells = {tuple(c['coordinate']): c['cached_value'] for c in packet['source']['cells']}
    statements = defaultdict(list)
    for item in answer['context_statements']:
        p = cell_coordinate(item['evidence_cell'])
        interval = exact_slice(cells[p], item['exact_excerpt'], item['occurrence_index'])
        scope = item['applicability']
        receiving = tuple(sorted(tables[t] for t in item['retaining_tables']))
        qualified = set()
        if scope['state'] == 'resolved':
            qualified = (set().union(*(points(a) for a in receiving)) if scope['scope'] == 'table'
                         else ranges(scope['source_ranges'], target))
        statements[p].append({'interval': (interval['start_byte'], interval['end_byte_exclusive']),
                              'receiving': receiving, 'state': scope['state'],
                              'qualified': qualified, 'role': item['role']})
    return {'roles': roles, 'headers': headers, 'axes': axes, 'excluded': excluded,
            'uncertain': uncertain, 'tables': tuple(sorted(tables.values())), 'statements': statements}


def metric():
    return {'compared_units': 0, 'agreed_units': 0, 'disagreed_units': 0,
            'unresolved_units': 0, 'not_comparable_units': 0, 'declared_unknown_units': 0, 'details': []}


def observe(result, coordinate, left, right, uncertain=False, incomparable=False, **extra):
    if incomparable:
        result['not_comparable_units'] += 1; status = 'not_comparable'
    elif uncertain:
        result['unresolved_units'] += 1; status = 'unresolved'
    else:
        result['compared_units'] += 1
        status = 'agreed' if left == right else 'disagreed'
        result[status + '_units'] += 1
    if status != 'agreed':
        result['details'].append({'coordinate': list(coordinate) if coordinate is not None else None,
                                  'status': status, 'reviewer_a': left, 'reviewer_b': right, **extra})


def compact_points(values):
    """Stable row runs make scope segmentation and source-range ordering irrelevant."""
    rows = defaultdict(list)
    for r, c in sorted(values):
        rows[r].append(c)
    out = []
    for r, columns in rows.items():
        first = previous = columns[0]
        for c in columns[1:]:
            if c != previous + 1:
                out.append([r, first, r + 1, previous + 1]); first = c
            previous = c
        out.append([r, first, r + 1, previous + 1])
    return out


def scope_at(statements, start, end):
    active = [s for s in statements if s['interval'][0] <= start and end <= s['interval'][1]]
    receiving = set(); qualified = set(); states = set(); roles = set()
    for item in active:
        receiving.update(item['receiving']); qualified.update(item['qualified'])
        states.add(item['state']); roles.add(item['role'])
    return {'retaining_tables': [list(a) for a in sorted(receiving)],
            'states': sorted(states), 'qualified_source_runs': compact_points(qualified)}, sorted(roles)


def compare(left_answer, right_answer, packet):
    left = normalized(left_answer, packet); right = normalized(right_answer, packet)
    cells = {tuple(c['coordinate']): c['cached_value'] for c in packet['source']['cells']
             if inside(packet['target_bounds'], c['coordinate'])}
    metrics = {name: metric() for name in ('record_role', 'header_membership', 'record_axis',
                                           'non_record_role', 'physical_occurrences', 'context_scope', 'context_role')}
    insufficient = not left_answer['evidence_sufficient'] or not right_answer['evidence_sufficient']
    for p in sorted(cells):
        a = sorted(left['roles'][p]); b = sorted(right['roles'][p])
        unknown = not a or not b or len(a) != 1 or len(b) != 1
        observe(metrics['record_role'], p, a, b, uncertain=unknown or p in left['uncertain']['record_role'] or p in right['uncertain']['record_role'])
        metrics['record_role']['declared_unknown_units'] += 'unresolved' in a or 'unresolved' in b
        if left['headers'][p] or right['headers'][p]:
            observe(metrics['header_membership'], p, sorted(left['headers'][p]), sorted(right['headers'][p]),
                    uncertain=unknown or p in left['uncertain']['header_membership'] or p in right['uncertain']['header_membership'])
        if left['axes'][p] or right['axes'][p]:
            observe(metrics['record_axis'], p, sorted(left['axes'][p]), sorted(right['axes'][p]),
                    uncertain=p in left['uncertain']['record_axis'] or p in right['uncertain']['record_axis'],
                    incomparable=not left['axes'][p] or not right['axes'][p])
        if left['excluded'][p] or right['excluded'][p]:
            a = sorted(left['excluded'][p]); b = sorted(right['excluded'][p])
            observe(metrics['non_record_role'], p, a, b, incomparable=not a or not b)
            metrics['non_record_role']['declared_unknown_units'] += 'unresolved' in a or 'unresolved' in b
    catalogs_match = left['tables'] == right['tables']
    observe(metrics['physical_occurrences'], None, [list(t) for t in left['tables']], [list(t) for t in right['tables']],
            uncertain=insufficient)
    for p in sorted(left['statements'].keys() | right['statements'].keys()):
        a = left['statements'][p]; b = right['statements'][p]
        boundaries = sorted({v for s in a+b for v in s['interval']})
        for start, end in zip(boundaries, boundaries[1:]):
            # Ignore unannotated and whitespace-only gaps. Joined/split equal-scope
            # statements compare equally; no statement wording is reconstructed.
            text = cells[p].encode()[start:end].decode('utf-8')
            if not text.strip() or not any(s['interval'][0] <= start and end <= s['interval'][1] for s in a+b):
                continue
            scope_a, role_a = scope_at(a, start, end); scope_b, role_b = scope_at(b, start, end)
            unresolved = p in left['uncertain']['context_scope'] or p in right['uncertain']['context_scope']
            extra = {'source_slice': {'start_byte': start, 'end_byte_exclusive': end}}
            observe(metrics['context_scope'], p, scope_a, scope_b, uncertain=unresolved,
                    incomparable=not catalogs_match, **extra)
            metrics['context_scope']['declared_unknown_units'] += 'unresolved' in scope_a['states'] or 'unresolved' in scope_b['states']
            observe(metrics['context_role'], p, role_a, role_b, **extra)
            metrics['context_role']['declared_unknown_units'] += 'unresolved' in role_a or 'unresolved' in role_b
    needs_adjudication = insufficient or any(m['disagreed_units'] or m['unresolved_units'] or m['not_comparable_units'] for m in metrics.values())
    return {'packet_id': packet['packet_id'], 'evidence_sufficient': not insufficient,
            'status': 'needs_human_adjudication' if needs_adjudication else 'provisional_agreement',
            'metrics': metrics,
            'explicit_uncertainties': {'reviewer_a': left_answer['uncertainties'], 'reviewer_b': right_answer['uncertainties']}}


def summarize(comparisons, family_by_packet, cohort_by_packet):
    groups = defaultdict(lambda: defaultdict(lambda: {
        'packets_with_compared_units': 0, 'packets_with_any_disagreement': 0,
        'packets_with_unresolved_units': 0, 'packets_with_not_comparable_units': 0,
        'compared_units': 0, 'agreed_units': 0, 'disagreed_units': 0,
        'unresolved_units': 0, 'not_comparable_units': 0, 'declared_unknown_units': 0}))
    packets_by_cohort = defaultdict(list)
    for item in comparisons:
        family = family_by_packet[item['packet_id']]
        cohort = cohort_by_packet[item['packet_id']]
        packets_by_cohort[cohort].append(item['packet_id'])
        for group in (None, family):
            for name, values in item['metrics'].items():
                out = groups[cohort, group][name]
                for key in ('compared_units', 'agreed_units', 'disagreed_units', 'unresolved_units', 'not_comparable_units', 'declared_unknown_units'):
                    out[key] += values[key]
                out['packets_with_compared_units'] += values['compared_units'] > 0
                out['packets_with_any_disagreement'] += values['disagreed_units'] > 0
                out['packets_with_unresolved_units'] += values['unresolved_units'] > 0
                out['packets_with_not_comparable_units'] += values['not_comparable_units'] > 0
    cohorts = {}
    for cohort, packet_ids in sorted(packets_by_cohort.items()):
        families = sorted({family_by_packet[p] for p in packet_ids})
        cohorts[cohort] = {
            'packet_count': len(packet_ids), 'source_family_count': len(families),
            'by_decision': dict(groups[cohort, None]),
            'by_family_and_decision': {family: dict(groups[cohort, family]) for family in families}}
    return {'contract': 'table.agreement.v1', 'packet_count': len(comparisons),
            'source_family_count': len(set(family_by_packet.values())),
            'units': 'Physical roles/header membership/axes use populated target cells; physical occurrence uses one complete table catalog per packet. Context uses exact nonwhitespace source spans split at both raters boundaries, with scope unions normalized to source coordinates. Different table catalogs make scope not comparable. Arbitrary local table IDs, list order and equivalent range segmentation do not affect comparison.',
            'limits': 'Descriptive human agreement, not correctness, model accuracy or a hard ceiling. Diagnostic and control agreement counts are reported separately, including within shared source families; they are never pooled. Controls may be recognizable or contain explicit source policy cues. Cell/span units within a packet and transformed packets within a family are correlated. Unclassified/conflicting roles and explicit decision uncertainty remain unresolved units. A declared unknown source role/applicability is a valid label: agreement on it counts and is separately reported under declared_unknown_units. All targets still require human adjudication and a versioned freeze before capability requests.',
            'by_cohort': cohorts,
            'packets': comparisons, 'capability_calls_allowed': False}
