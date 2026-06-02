from markdown_pdf import MarkdownPdf, Section
import os
import sys

def convert_md_to_pdf(md_file):
    if not os.path.exists(md_file):
        print(f"File not found: {md_file}")
        return

    pdf_file = os.path.splitext(md_file)[0] + ".pdf"
    
    print(f"Reading Markdown: {md_file}")
    with open(md_file, "r", encoding="utf-8") as f:
        md_text = f.read()

    pdf = MarkdownPdf(toc_level=2)
    
    # Add content
    # Note: markdown-pdf treats text as one section.
    # Images in Markdown (![alt](path)) are supported if paths are relative/absolute.
    pdf.add_section(Section(md_text))
    
    print(f"Writing PDF: {pdf_file}")
    try:
        pdf.save(pdf_file)
        print(f"Success! PDF saved to: {pdf_file}")
    except Exception as e:
        print(f"Error converting to PDF: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python md_to_pdf.py <md_file>")
        # Default for the user's current context
        default_file = "The_Golden_Book_of_Chemistry__visual_deutsch.md"
        if os.path.exists(default_file):
            convert_md_to_pdf(default_file)
    else:
        convert_md_to_pdf(sys.argv[1])
