import pdfplumber
import sys

def search_pdf(file_path, keywords):
    try:
        with pdfplumber.open(file_path) as pdf:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text()
                if text:
                    for keyword in keywords:
                        if keyword.lower() in text.lower():
                            print(f'--- Page {i+1} ---')
                            # Print lines containing any keyword
                            lines = text.split('\n')
                            for line in lines:
                                if any(k.lower() in line.lower() for k in keywords):
                                    print(line)
                            break
    except Exception as e:
        print(f'Error: {e}')

keywords = ['UART', 'USART', '串口', 'GPS', '光流', '数传', 'IMU']
search_pdf(sys.argv[1], keywords)
