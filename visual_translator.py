import os
import logging
import time
import re
import fitz  # PyMuPDF
from google.generativeai import GenerativeModel, configure

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

class VisualTranslator:
    def __init__(self, api_key, model_name=None):
        self.api_key = api_key
        if not self.api_key:
            logging.error("API Key missing.")
            raise ValueError("API Key not found.")
        
        # Use env var or default
        if not model_name:
            model_name = os.getenv("GEMINI_LLM", "gemini-1.5-flash")
            
        configure(api_key=self.api_key)
        self.model = GenerativeModel(model_name)
        logging.info(f"VisualTranslator initialized with model: {model_name}")

    def translate_text(self, text, target_language="deutsch", max_retries=5):
        """Translates text using Gemini with strict output instructions and rate limit handling."""
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
            except Exception as e:
                error_str = str(e)
                if "429" in error_str:
                    wait_time = 10 * (attempt + 1)  # Progressive backoff: 10s, 20s, 30s...
                    logging.warning(f"Rate limit hit (429). Waiting {wait_time} seconds before retry {attempt + 1}/{max_retries}...")
                    time.sleep(wait_time)
                else:
                    logging.error(f"Translation error: {e}")
                    return text  # Return original if non-recoverable error
        
        logging.error("Max retries exceeded for rate limit.")
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
    import sys
    
    API_KEY = os.getenv("GEMINI_API_KEY")
    if not API_KEY:
        print("Error: GEMINI_API_KEY environment variable not set.")
        sys.exit(1)

    target_lang = "deutsch"
    
    # Simple argument parsing: python visual_translator.py <file> [lang]
    if len(sys.argv) < 2:
        print("Usage: python visual_translator.py <pdf_file> [target_language]")
        # Default fallback for testing if file exists
        files = [f for f in os.listdir('.') if f.endswith('.pdf')]
        if files:
            print(f"No file specified. Using first found PDF: {files[0]}")
            translator = VisualTranslator(API_KEY)
            translator.process_pdf(files[0], target_lang)
        else:
            sys.exit(1)
    else:
        file_path = sys.argv[1]
        if len(sys.argv) > 2:
            target_lang = sys.argv[2]
            
        translator = VisualTranslator(API_KEY)
        translator.process_pdf(file_path, target_lang)
