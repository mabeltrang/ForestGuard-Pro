import os
from pypdf import PdfReader
from docx import Document
import pandas as pd


def extract_text_from_file(file_path: str) -> str:
    ext = os.path.splitext(file_path)[1].lower()
    text = ""

    try:
        if ext == ".pdf":
            reader = PdfReader(file_path)
            for page in reader.pages:
                extracted = page.extract_text()
                if extracted:
                    text += extracted + "\n"

        elif ext in [".docx", ".doc"]:
            text = extract_docx(file_path)

        elif ext in [".xlsx", ".xls"]:
            df_dict = pd.read_excel(file_path, sheet_name=None)
            for sheet_name, df in df_dict.items():
                text += f"\n[Hoja: {sheet_name}]\n"
                text += df.to_string(index=False) + "\n"

    except Exception as e:
        print(f"Error extrayendo {file_path}: {e}")

    return text


def extract_docx(file_path: str) -> str:
    """
    Extrae texto de un .docx de manera más inteligente:
    - Párrafos normales
    - Tablas: convierte cada fila en "cabecera: valor" para facilitar el regex
    - Preserva contexto de encabezados para que el regex sepa en qué sección está
    """
    doc = Document(file_path)
    parts = []

    for block in iter_blocks(doc):
        if block["type"] == "paragraph":
            txt = block["text"].strip()
            if txt:
                parts.append(txt)
        elif block["type"] == "table":
            parts.append(_table_to_text(block["table"]))

    return "\n".join(parts)


def iter_blocks(doc):
    """
    Itera párrafos y tablas del documento en el orden real del XML.
    python-docx expone doc.paragraphs y doc.tables por separado,
    pero aquí los entregamos en el orden que aparecen en el documento.
    """
    from docx.oxml.ns import qn
    body = doc.element.body

    for child in body:
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag

        if tag == "p":
            from docx.text.paragraph import Paragraph
            yield {"type": "paragraph", "text": Paragraph(child, doc).text}

        elif tag == "tbl":
            from docx.table import Table
            yield {"type": "table", "table": Table(child, doc)}


def _table_to_text(table) -> str:
    """
    Convierte una tabla en texto plano preservando contexto.
    Si la primera fila parece ser encabezado, produce líneas como:
    'Nombre especie: Cedrela odorata | Individuos: 8 | Volumen: 0,816 m3'
    Si no tiene encabezado claro, produce líneas separadas por |.
    """
    rows = []
    for row in table.rows:
        cells = [cell.text.strip() for cell in row.cells]
        # Eliminar celdas repetidas (python-docx repite celdas combinadas)
        seen = []
        for c in cells:
            if not seen or c != seen[-1]:
                seen.append(c)
        rows.append(seen)

    if not rows:
        return ""

    lines = []
    # Si primera fila tiene texto en todas las celdas → encabezado
    header = rows[0] if all(h for h in rows[0]) else None

    for i, row in enumerate(rows):
        if header and i == 0:
            lines.append(" | ".join(row))
            continue

        if header:
            pairs = []
            for h, v in zip(header, row):
                if v:
                    pairs.append(f"{h}: {v}")
            if pairs:
                lines.append(" | ".join(pairs))
        else:
            lines.append(" | ".join(c for c in row if c))

    return "\n".join(lines)
