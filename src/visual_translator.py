import os
import logging
import time
import re
import sys

import fitz  # PyMuPDF

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from claude_cli import ClaudeModel, ClaudeError  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

class VisualTranslator:
    def __init__(self, api_key=None, model_name=None):
        """api_key bleibt aus Kompatibilität erhalten, wird nicht mehr gebraucht."""
        self.model = ClaudeModel(model_name)
        logging.info("VisualTranslator nutzt die Claude CLI.")

    def translate_text(self, text, target_language="deutsch", max_retries=5):
        """Übersetzt Text über die Claude CLI, mit strikter Ausgabevorgabe und Wiederholung."""
        if not text.strip():
            return ""
        
        prompt = (
            f"Translate the following content to {target_language}. "
            "Return ONLY the translated text. "
            "Do not include any introductory or concluding remarks. "
            "Do not include notes.\n\n"
            f"Content:\n{text}"
        )
        
        for attempt in range(max_retries):
            try:
                response = self.model.generate_content(prompt)
                return response.text.strip()
            except ClaudeError as e:
                wait_time = 5 * (attempt + 1)
                logging.warning(f"Model call failed ({e}). Retry {attempt + 1}/{max_retries} in {wait_time}s...")
                time.sleep(wait_time)
            except Exception as e:  # noqa: BLE001
                logging.error(f"Translation error: {e}")
                return text  # Return original if non-recoverable error

        logging.error("Max retries exceeded.")
        return text

    def process_pdf(self, source_file, target_language="deutsch"):
        """
        Rotates through PDF pages, extracts text and images, translates text,
        and assembles a Markdown document with embedded images.
        """
        # Sanitize filename: replace spaces with underscores to avoid Markdown link issues
        base_name = os.path.splitext(os.path.basename(source_file))[0].replace(" ", "_")
        output_md = f"{base_name}_visual_{target_language}.md"
        media_dir = f"{base_name}_media"

        # Create media directory for images
        os.makedirs(media_dir, exist_ok=True)
        logging.info(f"Created media directory: {media_dir}")

        doc = fitz.open(source_file)
        logging.info(f"Opened PDF: {source_file} ({len(doc)} pages)")

        with open(output_md, 'w', encoding='utf-8') as f:
            f.write(f"# Translation of {base_name}\n\n")

            for page_index, page in enumerate(doc):
                display_page_num = page_index + 1
                logging.info(f"Processing Page {display_page_num}...")

                f.write(f"\n---\n## Page {display_page_num}\n\n")

                # 1. Extract and Save Images
                image_list = page.get_images(full=True)
                if image_list:
                    logging.info(f"Found {len(image_list)} images on page {display_page_num}.")
                    for img_index, img in enumerate(image_list, start=1):
                        xref = img[0]
                        base_image = doc.extract_image(xref)
                        image_bytes = base_image["image"]
                        image_ext = base_image["ext"]
                        
                        image_filename = f"p{display_page_num}_img{img_index}.{image_ext}"
                        image_path = os.path.join(media_dir, image_filename)
                        
                        with open(image_path, "wb") as img_file:
                            img_file.write(image_bytes)
                        
                        # Embed image in Markdown
                        f.write(f"![Image {img_index}]({image_path})\n\n")
                
                # 2. Extract Text
                text = page.get_text()
                if text.strip():
                    logging.info("Translating text...")
                    translated_text = self.translate_text(text, target_language)
                    f.write(translated_text + "\n\n")
                else:
                    logging.info("No text found on this page.")
        
        logging.info(f"Visual translation completed. Output: {output_md}")


if __name__ == "__main__":
    target_lang = "deutsch"
    
    # Simple argument parsing: python visual_translator.py <file> [lang]
    if len(sys.argv) < 2:
        print("Usage: python visual_translator.py <pdf_file> [target_language]")
        # Default fallback for testing if file exists
        files = [f for f in os.listdir('.') if f.endswith('.pdf')]
        if files:
            print(f"No file specified. Using first found PDF: {files[0]}")
            translator = VisualTranslator()
            translator.process_pdf(files[0], target_lang)
        else:
            sys.exit(1)
    else:
        file_path = sys.argv[1]
        if len(sys.argv) > 2:
            target_lang = sys.argv[2]
            
        translator = VisualTranslator()
        translator.process_pdf(file_path, target_lang)
