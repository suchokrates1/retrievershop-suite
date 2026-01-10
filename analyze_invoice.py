#!/usr/bin/env python3
"""
Skrypt do analizy faktury PDF i porównania z bazą danych
"""
import sys
import os

# Próba importu różnych bibliotek PDF
pdf_library = None
try:
    import PyPDF2
    pdf_library = 'PyPDF2'
except ImportError:
    pass

try:
    import pdfplumber
    pdf_library = 'pdfplumber'
except ImportError:
    pass

if not pdf_library:
    print("Brak biblioteki PDF. Instaluję pdfplumber...")
    os.system(f"{sys.executable} -m pip install pdfplumber")
    import pdfplumber
    pdf_library = 'pdfplumber'

# Odczyt faktury
pdf_path = r'C:\Users\sucho\Downloads\Faktura (1).pdf'

print("=" * 80)
print("ANALIZA FAKTURY")
print("=" * 80)
print()

invoice_text = ""
if pdf_library == 'pdfplumber':
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            print(f"=== STRONA {i+1} ===")
            text = page.extract_text()
            print(text)
            print()
            invoice_text += text + "\n\n"
else:
    with open(pdf_path, 'rb') as f:
        reader = PyPDF2.PdfReader(f)
        for i, page in enumerate(reader.pages):
            print(f"=== STRONA {i+1} ===")
            text = page.extract_text()
            print(text)
            print()
            invoice_text += text + "\n\n"

print()
print("=" * 80)
print("ZAPISUJĘ DO PLIKU")
print("=" * 80)

with open('invoice_content.txt', 'w', encoding='utf-8') as f:
    f.write(invoice_text)

print("Zapisano do invoice_content.txt")
