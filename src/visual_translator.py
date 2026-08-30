import os
import logging
import time
import re
import sys

import fitz  # PyMuPDF

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import llm  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

class VisualTranslator:
    def __init__(self, api_key=None, model_name=None, provider=None):
        """api_key bleibt aus Kompatibilität erhalten; Gemini holt ihn selbst."""
        self.model = llm.get_model(model_name, provider)
        logging.info("VisualTranslator nutzt Anbieter: %s", llm.resolve(provider))

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
            except llm.transient_errors() as e:
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
    import argparse

    parser = argparse.ArgumentParser(
        description="PDF seitenweise übersetzen, Bilder in Markdown einbetten")
    parser.add_argument("pdf_file", nargs="?", help="Quell-PDF")
    parser.add_argument("language", nargs="?", default="deutsch",
                        help="Zielsprache (Standard: deutsch)")
    parser.add_argument("--model", default=None,
                        help="Modellname beim gewählten Anbieter")
    llm.add_provider_argument(parser)
    args = parser.parse_args()

    source = args.pdf_file
    if not source:
        candidates = [f for f in os.listdir(".") if f.endswith(".pdf")]
        if not candidates:
            print("Kein PDF angegeben und keines im Verzeichnis gefunden.")
            sys.exit(1)
        source = candidates[0]
        print(f"Kein PDF angegeben. Verwende: {source}")

    translator = VisualTranslator(model_name=args.model, provider=args.provider)
    translator.process_pdf(source, args.language)
