from process_all import extract_pdfs

if __name__ == "__main__":
    rows = extract_pdfs()
    print(f"processed {len(rows)} PDFs")
