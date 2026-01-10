import PyPDF2
import sys

pdf_path = r'c:\Users\sucho\Downloads\Faktura (1).pdf'

with open(pdf_path, 'rb') as pdf_file:
    reader = PyPDF2.PdfReader(pdf_file)
    
    for page_num in range(len(reader.pages)):
        print(f"\n{'='*80}")
        print(f"STRONA {page_num + 1}")
        print(f"{'='*80}\n")
        text = reader.pages[page_num].extract_text()
        print(text)
