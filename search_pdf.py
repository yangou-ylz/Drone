import sys
from pdfminer.high_level import extract_pages
from pdfminer.layout import LTTextContainer

def search_pdf(file_path, keywords):
    results = []
    try:
        for page_layout in extract_pages(file_path):
            page_num = page_layout.pageid
            for element in page_layout:
                if isinstance(element, LTTextContainer):
                    text = element.get_text()
                    for kw in keywords:
                        if kw.lower() in text.lower():
                            results.append((page_num, kw, text.strip()))
    except Exception as e:
        print(f"Error: {e}")
    return results

file_path = "用户手册/匿名通信协议V7.pdf"
keywords = ["0xA0", "A0", "字符串", "文本"]
matches = search_pdf(file_path, keywords)

for page, kw, context in matches:
    print(f"Page {page} | Keyword: {kw}")
    print(f"Context: {context}")
    print("-" * 20)
