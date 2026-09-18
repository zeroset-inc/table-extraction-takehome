"""Validate one response using only its assigned offline review bundle."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


def inside(bounds, point):
    return bounds[0] <= point[0] < bounds[2] and bounds[1] <= point[1] < bounds[3]


TABLE_FIELDS = {'table_id', 'source_range', 'record_axis', 'primary_header_ranges',
                'record_ranges', 'repeated_header_ranges', 'reason'}
CONTEXT_ROLES = {'title', 'header', 'unit', 'definition', 'footnote', 'section',
                 'explanation', 'status_key', 'other', 'unresolved'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def cell_coordinate(value):
    require(isinstance(value, str), 'Use an Excel A1 coordinate string.')
    match = re.fullmatch(r'([A-Z]{1,3})([1-9][0-9]*)', value or '')
    require(match is not None, 'Use an Excel A1 coordinate.')
    column = 0
    for letter in match[1]:
        column = 26 * column + ord(letter) - 64
    return int(match[2]) - 1, column - 1


def source_range(value, target):
    require(isinstance(value, str), 'A source range is required.')
    parts = value.split(':')
    require(len(parts) in (1, 2), 'Invalid range.')
    a = cell_coordinate(parts[0]); b = cell_coordinate(parts[-1])
    require(a[0] <= b[0] and a[1] <= b[1], 'Range endpoints are reversed.')
    require(inside(target, a) and inside(target, b), 'Annotation outside extraction target.')
    return [*a, b[0] + 1, b[1] + 1]


def exact_slice(text, excerpt, occurrence):
    require(isinstance(text, str) and isinstance(excerpt, str) and bool(excerpt), 'Quote nonempty source text exactly.')
    require(type(occurrence) is int and occurrence >= 0, 'Invalid excerpt occurrence index.')
    positions = []; start = 0
    while True:
        found = text.find(excerpt, start)
        if found < 0:
            break
        positions.append(found); start = found + 1
    require(occurrence < len(positions), 'Excerpt occurrence is absent from the source cell.')
    start = positions[occurrence]
    first = len(text[:start].encode('utf-8'))
    return {'start_byte': first, 'end_byte_exclusive': first + len(excerpt.encode('utf-8'))}


def validate_response(answer, packet, reviewer_id):
    require(isinstance(answer, dict), 'The response must be a JSON object.')
    require(len(json.dumps(answer, ensure_ascii=False).encode()) <= 256 * 1024, 'Response byte budget exceeded.')
    require(answer['contract'] == 'table.annotation.v1', 'Unknown response contract.')
    require(answer['packet_id'] == packet['packet_id'] and answer['reviewer_id'] == reviewer_id,
            'Submission identity mismatch.')
    require(answer['completion'] in ('pending', 'complete'), 'Unknown completion status.')
    if answer['completion'] == 'pending':
        return {'status': 'pending'}
    require(isinstance(answer['human_name'], str) and bool(answer['human_name'].strip()), 'Human name is required.')
    require(type(answer['independent_review']) is bool and
            type(answer['prior_access_to_model_answers_or_gold']) is bool, 'Independence declarations are required.')
    require(type(answer['evidence_sufficient']) is bool, 'Evidence sufficiency is required.')
    require(isinstance(answer['reasoning'], str) and bool(answer['reasoning'].strip()), 'An overall rationale is required.')
    for key, limit in [('tables', 16), ('non_record_ranges', 256), ('context_statements', 128), ('uncertainties', 128)]:
        require(isinstance(answer[key], list) and len(answer[key]) <= limit, 'Response item budget exceeded: ' + key)
    target = packet['target_bounds']; tables = {}
    for table in answer['tables']:
        require(isinstance(table, dict) and set(table) == TABLE_FIELDS, 'Each table must be an object with the fields shown in README.md.')
        identifier = table['table_id']
        require(isinstance(identifier, str) and re.fullmatch(r'T[1-9][0-9]*', identifier) is not None,
                'Use local table IDs T1, T2, etc.')
        require(identifier not in tables, 'Duplicate table identity.')
        require(table['record_axis'] in ('rows', 'columns'), 'Choose a record axis or record uncertainty separately.')
        area = source_range(table['source_range'], target)
        require(all(max(area[0], other[0]) >= min(area[2], other[2]) or
                    max(area[1], other[1]) >= min(area[3], other[3]) for other in tables.values()),
                'Physical table occurrences overlap; record alternative interpretations under uncertainties.')
        for key in ('primary_header_ranges', 'record_ranges', 'repeated_header_ranges'):
            require(isinstance(table[key], list) and len(table[key]) <= 256, 'Header and record range budget exceeded.')
            for value in table[key]:
                source_range(value, area)
        require(bool(table['primary_header_ranges']) and bool(table['record_ranges']), 'A proposed table needs headers and records.')
        require(isinstance(table['reason'], str) and bool(table['reason'].strip()), 'Table rationale required.')
        tables[identifier] = area
    for item in answer['non_record_ranges']:
        require(isinstance(item, dict), 'Each non_record_ranges entry must be an object.')
        source_range(item['source_range'], target)
        require(item['role'] in ('section', 'title', 'note', 'other', 'unresolved'), 'Unknown non-record role.')
        require(bool(item['reason']), 'Non-record rationale required.')
    for item in answer['uncertainties']:
        require(isinstance(item, dict), 'Each uncertainties entry must be an object.')
        source_range(item['source_range'], target)
        require(item['decision'] in ('record_role', 'header_membership', 'record_axis', 'context_scope'), 'Unknown disputed decision.')
        require(isinstance(item['supported_options'], list) and bool(item['supported_options']), 'List the interpretations or missing evidence.')
        require(bool(item['reason']), 'Uncertainty rationale required.')
    require(bool(tables) or bool(answer['uncertainties']) or bool(answer['non_record_ranges']), 'Empty annotation.')
    if not answer['evidence_sufficient']:
        require(bool(answer['uncertainties']), 'Identify the missing evidence under uncertainties.')
    source = {tuple(c['coordinate']): c['cached_value'] for c in packet['source']['cells']}
    slices = []
    for item in answer['context_statements']:
        require(isinstance(item, dict), 'Each context_statements entry must be an object.')
        point = cell_coordinate(item['evidence_cell'])
        require(inside(target, point) and point in source, 'Context evidence must be a populated target cell.')
        slices.append({'evidence_cell': item['evidence_cell'],
                       **exact_slice(source[point], item['exact_excerpt'], item['occurrence_index'])})
        require(item['role'] in CONTEXT_ROLES, 'Unknown context role.')
        require(len(set(item['retaining_tables'])) == len(item['retaining_tables']) and
                all(t in tables for t in item['retaining_tables']), 'Unknown or duplicate retaining table.')
        scope = item['applicability']
        require(isinstance(scope, dict), 'Context applicability must be an object.')
        require(scope['state'] in ('resolved', 'unresolved'), 'Unknown applicability state.')
        require(scope['scope'] in ('table', 'fields', 'records', 'field_records', 'unresolved'), 'Unknown applicability scope.')
        require(isinstance(scope['source_ranges'], list) and len(scope['source_ranges']) <= 256, 'Scope range budget exceeded.')
        if scope['state'] == 'unresolved':
            require(scope['scope'] == 'unresolved' and not scope['source_ranges'], 'Unresolved applicability must not assert a range.')
        else:
            require(bool(item['retaining_tables']) and scope['scope'] != 'unresolved', 'Resolved scope needs a retaining table.')
            require(bool(scope['source_ranges']) == (scope['scope'] != 'table'), 'Table scope has no ranges; narrower scope needs ranges.')
        for value in scope['source_ranges']:
            area = source_range(value, target)
            require(any(inside(tables[t], area[:2]) and inside(tables[t], [area[2]-1, area[3]-1])
                        for t in item['retaining_tables']), 'Scope range falls outside the retaining tables.')
        require(bool(item['reason']), 'Context rationale required.')
    blind = answer['independent_review'] and not answer['prior_access_to_model_answers_or_gold']
    return {'status': 'complete', 'blind_independent_attested': blind,
            'human_name': answer['human_name'].strip(), 'derived_source_slices': slices}


def bundle_path(root, relative):
    path = (root / relative).resolve()
    require(path.is_relative_to(root), 'Choose a file inside this review bundle: ' + str(relative))
    return path


def read_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as error:
        raise ValueError(f'{path.name}: invalid JSON at line {error.lineno}, column {error.colno}: {error.msg}') from error


def validate_file(root, response_path):
    root = root.resolve()
    manifest = read_json(root / 'manifest.json')
    response_path = bundle_path(root, response_path)
    entry = next((entry for entry in manifest['packets']
                  if bundle_path(root, entry['response']) == response_path), None)
    require(entry is not None, 'Choose a response listed in this bundle\'s manifest.json.')
    for relative in ('validate_response.py', 'README.md', 'POLICY.md', entry['source_json'], entry['view']):
        path = bundle_path(root, relative)
        require(hashlib.sha256(path.read_bytes()).hexdigest() == manifest['immutable_files'][relative],
                'Bundle file changed: ' + relative + '. Restore it from the original ZIP before validating.')
    packet = read_json(bundle_path(root, entry['source_json']))
    require(packet['packet_id'] == entry['packet_id'] and packet['contract'] == manifest['contract'],
            'Packet identity differs from the bundle manifest.')
    return {'packet_id': entry['packet_id'],
            **validate_response(read_json(response_path), packet, manifest['reviewer_id'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--validate', required=True, type=Path, metavar='RESPONSE.json',
                        help='Response path relative to this script\'s bundle directory, or an absolute path within it.')
    args = parser.parse_args()
    try:
        result = validate_file(Path(__file__).resolve().parent, args.validate)
    except KeyError as error:
        print(f'Invalid response or bundle: missing required field {error.args[0]!r}. Check the form in README.md.', file=sys.stderr)
        return 1
    except (TypeError, AttributeError) as error:
        print(f'Invalid JSON value type: {error}. Check the object and array shapes in README.md.', file=sys.stderr)
        return 1
    except (ValueError, OSError) as error:
        print(f'Validation failed: {error}', file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    if result['status'] == 'pending':
        print('Pending response: annotations are not checked until completion is set to complete.', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
