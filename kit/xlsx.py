"""A small but real .xlsx writer: shared strings, styles, merges, several sheets,
sheet visibility, and formulas that carry a cached result.

Enough of the format to produce workbooks that behave like the ones customers
send us. Deterministic output, so a rebuild is byte-identical.
"""
import zipfile
from xml.sax.saxutils import escape

# Number-format ids. 0 is General; 164+ are custom, declared in numFmts.
GENERAL, DATE, MONTH_YEAR, CURRENCY, PERCENT, IDENTIFIER = 0, 14, 164, 165, 166, 167
CUSTOM = {MONTH_YEAR: 'mmm-yy', CURRENCY: '#,##0.00;(#,##0.00)', PERCENT: '0.0%',
          IDENTIFIER: '00000000'}

# Fill equivalence classes. Index 0 and 1 are reserved by the format.
FILLS = ['none', 'gray125', 'D9E1F2', 'FCE4D6', 'E2EFDA', 'FFF2CC']
# Border edge sets, as (top, right, bottom, left) booleans.
BORDERS = [(0, 0, 0, 0), (1, 1, 1, 1), (0, 0, 1, 0), (1, 0, 1, 0)]


class Style:
    """One cell format: bold, a fill class, a border set and a number format."""

    __slots__ = ('bold', 'fill', 'border', 'number_format')

    def __init__(self, bold=False, fill=0, border=0, number_format=GENERAL):
        self.bold, self.fill, self.border, self.number_format = bold, fill, border, number_format

    def key(self):
        return (self.bold, self.fill, self.border, self.number_format)


DEFAULT = Style()


class Sheet:
    def __init__(self, name, visibility='visible'):
        self.name = name
        self.visibility = visibility
        self.cells = {}          # (row, column) -> value | {'formula', 'cached'}
        self.styles = {}         # (row, column) -> Style
        self.merges = []         # [row, column, row_end, column_end], half-open
        self.widths = {}

    def put(self, row, column, value, style=None):
        self.cells[row, column] = value
        if style is not None:
            self.styles[row, column] = style
        return self

    def merge(self, row, column, row_end, column_end):
        self.merges.append([row, column, row_end, column_end])
        return self


def reference(point):
    row, column = point
    name, column = '', column + 1
    while column:
        column, rem = divmod(column - 1, 26)
        name = chr(65 + rem) + name
    return f'{name}{row + 1}'


def _styles_part(order):
    fonts = ('<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
             '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>')
    fills = ['<fill><patternFill patternType="none"/></fill>',
             '<fill><patternFill patternType="gray125"/></fill>']
    for colour in FILLS[2:]:
        fills.append(f'<fill><patternFill patternType="solid"><fgColor rgb="FF{colour}"/>'
                     f'<bgColor indexed="64"/></patternFill></fill>')
    borders = []
    for top, right, bottom, left in BORDERS:
        edges = ''.join(
            f'<{name}{" style=\"thin\"" if flag else ""}/>'
            for name, flag in (('left', left), ('right', right), ('top', top), ('bottom', bottom)))
        borders.append(f'<border>{edges}<diagonal/></border>')
    numfmts = ''.join(f'<numFmt numFmtId="{i}" formatCode="{escape(code)}"/>'
                      for i, code in sorted(CUSTOM.items()))
    xfs = []
    for bold, fill, border, number_format in order:
        applied = ' applyNumberFormat="1"' if number_format != GENERAL else ''
        xfs.append(f'<xf numFmtId="{number_format}" fontId="{1 if bold else 0}" fillId="{fill}" '
                   f'borderId="{border}" xfId="0"{applied} applyFont="1" applyFill="1" applyBorder="1"/>')
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<numFmts count="{len(CUSTOM)}">{numfmts}</numFmts>{fonts}'
            f'<fills count="{len(fills)}">{"".join(fills)}</fills>'
            f'<borders count="{len(borders)}">{"".join(borders)}</borders>'
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            f'<cellXfs count="{len(xfs)}">{"".join(xfs)}</cellXfs>'
            '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
            '</styleSheet>')


def _sheet_part(sheet, shared, style_index):
    rows = {}
    for point in sorted(sheet.cells):
        rows.setdefault(point[0], []).append(point)
    body = []
    for row in sorted(rows):
        cells = []
        for point in rows[row]:
            value = sheet.cells[point]
            style = sheet.styles.get(point, DEFAULT)
            attrs = f' s="{style_index[style.key()]}"' if style.key() in style_index else ''
            formula = None
            if isinstance(value, dict):
                formula, value = value.get('formula'), value.get('cached')
            inner = ''
            if isinstance(value, bool):
                attrs += ' t="b"'
                inner = f'<v>{int(value)}</v>'
            elif isinstance(value, str):
                if formula:
                    attrs += ' t="str"'
                    inner = f'<v>{escape(value)}</v>'
                else:
                    attrs += ' t="s"'
                    inner = f'<v>{shared[value]}</v>'
            elif value is not None:
                inner = f'<v>{value!r}</v>' if isinstance(value, float) else f'<v>{value}</v>'
            if formula:
                inner = f'<f>{escape(formula)}</f>' + inner
            cells.append(f'<c r="{reference(point)}"{attrs}>{inner}</c>')
        body.append(f'<r r="{row + 1}">{"".join(cells)}</r>'.replace('<r ', '<row ', 1)
                    .replace('</r>', '</row>'))
    merges = ''
    if sheet.merges:
        entries = ''.join(
            f'<mergeCell ref="{reference((m[0], m[1]))}:{reference((m[2] - 1, m[3] - 1))}"/>'
            for m in sheet.merges)
        merges = f'<mergeCells count="{len(sheet.merges)}">{entries}</mergeCells>'
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<sheetData>{"".join(body)}</sheetData>{merges}</worksheet>')


def write(path, sheets):
    """Write one workbook. `sheets` is a list of Sheet, in tab order."""
    strings, shared = [], {}
    style_index = {}
    for sheet in sheets:
        for point, value in sorted(sheet.cells.items()):
            text = value.get('cached') if isinstance(value, dict) else value
            is_formula = isinstance(value, dict) and value.get('formula')
            if isinstance(text, str) and not isinstance(text, bool) and not is_formula:
                if text not in shared:
                    shared[text] = len(strings)
                    strings.append(text)
        for style in list(sheet.styles.values()) + [DEFAULT]:
            style_index.setdefault(style.key(), len(style_index))
    order = sorted(style_index, key=style_index.get)

    content = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types '
               'xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
               '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
               '<Default Extension="xml" ContentType="application/xml"/>'
               '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
               '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
               '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>']
    for index in range(1, len(sheets) + 1):
        content.append(f'<Override PartName="/xl/worksheets/sheet{index}.xml" '
                       'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>')
    content.append('</Types>')

    tabs = ''.join(
        f'<sheet name="{escape(sheet.name)}" sheetId="{i}" r:id="rId{i}"'
        + ('' if sheet.visibility == 'visible' else f' state="{sheet.visibility}"') + '/>'
        for i, sheet in enumerate(sheets, 1))
    relations = ''.join(
        f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        f'relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
        for i in range(1, len(sheets) + 1))
    tail = len(sheets) + 1
    parts = {
        '[Content_Types].xml': ''.join(content),
        '_rels/.rels': '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships '
                       'xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                       '<Relationship Id="rIdWorkbook" Type="http://schemas.openxmlformats.org/'
                       'officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        'xl/_rels/workbook.xml.rels': '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships '
                                      'xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                                      + relations +
                                      f'<Relationship Id="rId{tail}" Type="http://schemas.openxmlformats.org/'
                                      'officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/>'
                                      f'<Relationship Id="rId{tail + 1}" Type="http://schemas.openxmlformats.org/'
                                      'officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>',
        'xl/workbook.xml': '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook '
                           'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                           'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                           f'<sheets>{tabs}</sheets></workbook>',
        'xl/styles.xml': _styles_part(order),
        'xl/sharedStrings.xml': '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><sst '
                                'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                                f'count="{len(strings)}" uniqueCount="{len(strings)}">'
                                + ''.join(f'<si><t xml:space="preserve">{escape(s)}</t></si>' for s in strings)
                                + '</sst>',
    }
    for index, sheet in enumerate(sheets, 1):
        parts[f'xl/worksheets/sheet{index}.xml'] = _sheet_part(sheet, shared, style_index)
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as package:
        for name in sorted(parts):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            package.writestr(info, parts[name])
