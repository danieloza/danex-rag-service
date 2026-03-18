from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
import os

def create_pdf_report(filename, title, content_text):
    reports_dir = "reports"
    os.makedirs(reports_dir, exist_ok=True)
    filepath = os.path.join(reports_dir, filename)

    doc = SimpleDocTemplate(filepath, pagesize=letter)
    styles = getSampleStyleSheet()
    
    # Custom Styles
    title_style = styles['Heading1']
    title_style.textColor = colors.HexColor("#1e3a8a") # Blue 800
    
    body_style = styles['Normal']
    body_style.fontSize = 11
    body_style.leading = 14

    story = []

    # Add Title
    story.append(Paragraph(title, title_style))
    story.append(Spacer(1, 20))

    # Add Content
    paragraphs = content_text.split('\n')
    for p in paragraphs:
        if p.strip():
            story.append(Paragraph(p, body_style))
            story.append(Spacer(1, 10))

    # Footer/Watermark
    story.append(Spacer(1, 30))
    footer_style = ParagraphStyle('Footer', parent=styles['Normal'], fontSize=8, textColor=colors.gray)
    story.append(Paragraph("Wygenerowano automatycznie przez Danex RAG AI Assistant", footer_style))

    doc.build(story)
    return filepath
