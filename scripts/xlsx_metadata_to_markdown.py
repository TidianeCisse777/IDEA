#!/usr/bin/env python3
"""Turn a metadata sheet of a lab workbook (Title, Description, then a column table starting with
column_ordinal) into a Markdown document for the warehouse knowledge base (add_warehouse_document.py).

    python scripts/xlsx_metadata_to_markdown.py classeur.xlsx "copepod abund&biomass-metadata" out.md

Text is copied as is: one paragraph per column (« N. NAME (type; unité) : description »), so that long
dictionaries split into searchable sections. Needs openpyxl.
"""

from __future__ import annotations

import sys
from pathlib import Path


def clean(value) -> str:
    return str(value).replace('_x000D_', '').replace('\r', '').strip() if value is not None else ''


def convert(workbook: Path, sheet: str) -> str:
    import openpyxl
    rows = [[clean(v) for v in row] for row in
            openpyxl.load_workbook(workbook, read_only=True, data_only=True)[sheet].iter_rows(values_only=True)]
    rows = [r for r in rows if any(r)]
    out, header = [], None
    for row in rows:
        values = [v for v in row if v]
        if header is not None:
            item = dict(zip(header, row))
            details = '; '.join(f'{k} : {item[k]}' for k in header
                                if k not in ('column_ordinal', 'column_name', 'description') and item.get(k))
            out.append(f"**{item.get('column_ordinal', '')}. {item.get('column_name', '')}** ({details}) : "
                       f"{item.get('description', '')}\n")
        elif row and row[0].lower() == 'column_ordinal':
            header = [h.lower() for h in row]
            out.append(f'## Colonnes (feuille « {sheet} »)\n')
        elif row[0].lower() == 'title':
            out.insert(0, f'# {values[1] if len(values) > 1 else sheet}\n')
        else:
            out.append(f'## {values[0]}\n\n' + '\n\n'.join(values[1:]) + '\n' if len(values) > 1 else values[0] + '\n')
    return f'Source : classeur « {workbook.name} », feuille « {sheet} » (texte copié tel quel).\n\n' if not out else \
        out[0] + f'\nSource : classeur « {workbook.name} », feuille « {sheet} » (texte copié tel quel).\n\n' + '\n'.join(out[1:])


if __name__ == '__main__':
    workbook, sheet, target = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    target.write_text(convert(workbook, sheet), encoding='utf-8')
    print(target)
