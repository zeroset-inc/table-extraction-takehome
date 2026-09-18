"""Read a workbook back the way the ingestion service does.

Stdlib only. Cached values are what the workbook last stored; nothing is ever
recalculated. A formula cell keeps its cached result and is marked, but the
expression itself never reaches a packet.

Style information is reduced before it leaves here: a fill becomes an
*equivalence class*, not a colour, and a number format becomes a category. Two
cells that look alike are comparable; neither is readable as presentation.
"""
import xml.etree.ElementTree as ET
import zipfile

MAX_PART_BYTES = 64 * 1024 * 1024
BUILTIN_DATE = set(range(14, 23)) | set(range(45, 48))


def short(node):
    return node.tag.rsplit('}', 1)[-1]


def coordinate(ref):
    letters = ''.join(c for c in ref if c.isalpha())
    digits = ''.join(c for c in ref if c.isdigit())
    column = 0
    for c in letters:
        column = column * 26 + ord(c) - 64
    return int(digits) - 1, column - 1


def address(point):
    row, column = point
    name, column = '', column + 1
    while column:
        column, rem = divmod(column - 1, 26)
        name = chr(65 + rem) + name
    return f'{name}{row + 1}'


def range_label(bounds):
    return address((bounds[0], bounds[1])) + ':' + address((bounds[2] - 1, bounds[3] - 1))


def number_format_category(number_format, code):
    """The categories the planner is allowed to see. Never the format string."""
    if number_format == 0 and not code:
        return 'general'
    text = (code or '').lower()
    if number_format in BUILTIN_DATE or any(t in text for t in ('yy', 'mmm', 'dd/', 'd-m')):
        return 'date_time'
    if '%' in text:
        return 'percentage'
    if any(t in text for t in ('$', '£', '€', '#,##0.00')):
        return 'currency'
    if text and set(text) <= {'0'} and len(text) > 1:
        return 'zero_padded_identifier'
    return 'general' if number_format == 0 else 'other'


def _package(path):
    with zipfile.ZipFile(path) as package:
        def part(member):
            if member not in package.namelist():
                return None
            assert package.getinfo(member).file_size <= MAX_PART_BYTES, member
            return ET.fromstring(package.read(member))
        return {
            'workbook': part('xl/workbook.xml'),
            'rels': part('xl/_rels/workbook.xml.rels'),
            'styles': part('xl/styles.xml'),
            'strings': part('xl/sharedStrings.xml'),
            'members': package.namelist(),
            'read': lambda m: ET.fromstring(package.read(m)),
        }, zipfile.ZipFile(path)


def _styles(tree):
    """cellXfs index -> (bold, fill class, border bitmask, number-format category)."""
    if tree is None:
        return {0: (0, 0, 0, 'general')}
    for node in tree.iter():
        node.tag = short(node)
    bold = [node.find('b') is not None for node in tree.find('fonts')] if tree.find('fonts') is not None else [False]
    borders = []
    for border in (tree.find('borders') or []):
        mask = 0
        for bit, name in ((1, 'top'), (2, 'right'), (4, 'bottom'), (8, 'left')):
            edge = border.find(name)
            if edge is not None and edge.get('style') not in (None, '', 'none'):
                mask |= bit
        borders.append(mask)
    custom = {int(n.get('numFmtId')): n.get('formatCode', '')
              for n in tree.findall('./numFmts/numFmt')}
    result = {}
    for index, xf in enumerate(tree.find('cellXfs') or []):
        number_format = int(xf.get('numFmtId', '0'))
        result[index] = (int(bold[int(xf.get('fontId', '0'))]),
                         int(xf.get('fillId', '0')),
                         borders[int(xf.get('borderId', '0'))] if borders else 0,
                         number_format_category(number_format, custom.get(number_format)))
    return result or {0: (0, 0, 0, 'general')}


def sheets(path):
    """[(name, visibility)] in tab order."""
    parts, package = _package(path)
    try:
        result = []
        for node in parts['workbook'].iter():
            if short(node) == 'sheet':
                result.append((node.get('name'), node.get('state') or 'visible'))
        return result
    finally:
        package.close()


def worksheet(path, sheet):
    """Return (cells, merges) for one worksheet.

    cells: {(row, column): {cached_value, kind, formula_cache, style}}
    merges: [[row, column, row_end, column_end]] clipped to nothing else.
    """
    parts, package = _package(path)
    try:
        strings = []
        if parts['strings'] is not None:
            for si in parts['strings']:
                strings.append(''.join(t.text or '' for t in si.iter() if short(t) == 't'))
        style_map = _styles(parts['styles'])
        relations = {n.get('Id'): n.get('Target') for n in (parts['rels'] or [])}
        member = None
        for node in parts['workbook'].iter():
            if short(node) == 'sheet' and node.get('name') == sheet:
                rid = node.get('{http://schemas.openxmlformats.org/officeDocument/2006/'
                               'relationships}id')
                target = relations[rid]
                member = 'xl/' + target.lstrip('/')
        assert member is not None, f'worksheet {sheet!r} not found in {path}'
        tree = ET.fromstring(package.read(member))

        cells, merges = {}, []
        for node in tree.iter():
            tag = short(node)
            if tag == 'mergeCell':
                a, b = node.get('ref').split(':')
                start, end = coordinate(a), coordinate(b)
                merges.append([start[0], start[1], end[0] + 1, end[1] + 1])
                continue
            if tag != 'c':
                continue
            point = coordinate(node.get('r'))
            kind = node.get('t')
            style = style_map.get(int(node.get('s', '0')), (0, 0, 0, 'general'))
            formula = next((c for c in node if short(c) == 'f'), None)
            value_node = next((c for c in node if short(c) == 'v'), None)
            inline = next((c for c in node if short(c) == 'is'), None)
            cached, cell_kind = None, 'text'
            if inline is not None:
                cached = ''.join(t.text or '' for t in inline.iter() if short(t) == 't')
            elif value_node is not None and value_node.text is not None:
                raw = value_node.text
                if kind == 's':
                    cached = strings[int(raw)]
                elif kind == 'b':
                    cached, cell_kind = raw == '1', 'boolean'
                elif kind in ('str', 'inlineStr'):
                    cached = raw
                else:
                    number = float(raw)
                    cached = int(number) if number.is_integer() else number
                    cell_kind = 'numeric'
            elif formula is None:
                continue                      # formatting-only cell
            cells[point] = {'cached_value': cached, 'kind': cell_kind,
                            'formula_cache': 'cached_unverified' if formula is not None else None,
                            'style': list(style)}
        return {p: c for p, c in cells.items()
                if c['cached_value'] is not None or c['formula_cache']}, merges
    finally:
        package.close()
