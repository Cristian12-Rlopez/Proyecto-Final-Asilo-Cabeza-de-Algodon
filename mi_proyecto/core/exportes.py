"""Exportación de reportes a PDF (reportlab) y Excel (openpyxl). Sin dependencias de Django."""
from io import BytesIO
from xml.sax.saxutils import escape

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def exportar_pdf(rep):
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=24, rightMargin=24,
                            topMargin=24, bottomMargin=24, title=rep['titulo'])
    est = getSampleStyleSheet()
    celda = est['BodyText'].clone('celda', fontSize=7.5, leading=9)
    cab = est['BodyText'].clone('cab', fontSize=8, leading=10, textColor=colors.white)
    elementos = [Paragraph('Asilo Cabeza de Algodón', est['Title']),
                 Paragraph(escape(rep['titulo']), est['Heading2'])]
    for linea in rep.get('subtitulo', []):
        elementos.append(Paragraph(escape(linea), est['Normal']))
    elementos.append(Spacer(1, 8))

    datos = [[Paragraph(escape(str(c)), cab) for c in rep['columnas']]]
    for fila in rep['filas']:
        datos.append([Paragraph(escape(str(v)), celda) for v in fila])
    if len(datos) == 1:
        datos.append([Paragraph('Sin registros en el período seleccionado.', celda)] +
                     [''] * (len(rep['columnas']) - 1))
    tabla = Table(datos, repeatRows=1)
    tabla.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#047857')),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#9ca3af')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f3f4f6')]),
    ]))
    elementos.append(tabla)
    if rep.get('totales'):
        elementos.append(Spacer(1, 10))
        for etiqueta, valor in rep['totales']:
            elementos.append(Paragraph(f'<b>{escape(str(etiqueta))}:</b> {escape(str(valor))}', est['Normal']))
    doc.build(elementos)
    return buf.getvalue()


def exportar_xlsx(rep):
    wb = Workbook()
    ws = wb.active
    ws.title = rep['titulo'][:30].replace('/', '-')
    ws.append(['Asilo Cabeza de Algodón'])
    ws.append([rep['titulo']])
    for linea in rep.get('subtitulo', []):
        ws.append([linea])
    ws.append([])
    ws['A1'].font = Font(bold=True, size=14)
    ws['A2'].font = Font(bold=True, size=12)
    fila_cab = ws.max_row + 1
    ws.append(list(rep['columnas']))
    for celda in ws[fila_cab]:
        celda.font = Font(bold=True, color='FFFFFF')
        celda.fill = PatternFill('solid', fgColor='047857')
        celda.alignment = Alignment(wrap_text=True, vertical='top')
    for fila in rep['filas']:
        ws.append([str(v) for v in fila])
    if rep.get('totales'):
        ws.append([])
        for etiqueta, valor in rep['totales']:
            ws.append([etiqueta, valor])
            ws.cell(ws.max_row, 1).font = Font(bold=True)
    for i, _ in enumerate(rep['columnas'], start=1):
        ancho = max([len(str(rep['columnas'][i - 1]))] +
                    [len(str(f[i - 1])) for f in rep['filas']] or [10])
        ws.column_dimensions[get_column_letter(i)].width = min(max(ancho + 2, 12), 55)
    for fila in ws.iter_rows(min_row=fila_cab + 1):
        for celda in fila:
            celda.alignment = Alignment(wrap_text=True, vertical='top')
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
