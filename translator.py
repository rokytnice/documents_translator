import os
import pdfplumber
import textwrap
import time
import logging
from google.generativeai import GenerativeModel, configure
from ebooklib import epub, ITEM_DOCUMENT  # Added for EPUB
from bs4 import BeautifulSoup  # Added for parsing EPUB HTML content

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Set up API key and language (default)
API_KEY = os.getenv("GEMINI_API_KEY")
LANGUAGE = "deutsch"  # Default language, can be overridden by user input


def configure_genai():
    """
    Configures the Generative AI model.
    """
    if not API_KEY:
        logging.error("API key not found in environment variables.")
        return None
    configure(api_key=API_KEY)

    # Use the model from the GEMINI_LLM env var, or the specified default
    default_model = "gemini-1.5-flash-lite-preview-06-17"
    model_name = os.getenv("GEMINI_LLM", default_model)

    logging.info(f"Using Generative AI model: {model_name}")

    return GenerativeModel(model_name)


def get_translation_with_genai(model, content, max_retries=3):
    """
    Uses the Generative AI model to perform translations.
    Returns the translation and the character counts for input and output.
    Retries on rate limit errors (429).
    """
    logging.info("Generating %s translation with Google Gemini API.", LANGUAGE)

    for attempt in range(max_retries):
        try:
            # Use the global LANGUAGE variable, which is updated by user input
            prompt = f"Translate the following content to {LANGUAGE}. Return ONLY the translated text. Do not include any introductory or concluding remarks. Do not include notes.\\n\\nContent:\\n{content}"
            response = model.generate_content(prompt)
            response_text = response.text
            logging.info("Translation received: %s", response_text)
            return response_text, len(content), len(response_text)
        except Exception as e:
            error_str = str(e)
            if "429" in error_str:
                # Rate limit error - extract retry delay if possible
                retry_delay = 60  # Default wait time
                if "retry in" in error_str.lower():
                    try:
                        import re
                        match = re.search(r'retry in (\d+\.?\d*)', error_str.lower())
                        if match:
                            retry_delay = int(float(match.group(1))) + 5  # Add buffer
                    except:
                        pass
                logging.warning("Rate limit hit (attempt %d/%d). Waiting %d seconds...",
                              attempt + 1, max_retries, retry_delay)
                time.sleep(retry_delay)
            else:
                logging.error("Error during translation: %s", e)
                return "Error in translation.", len(content), 0

    logging.error("Max retries exceeded for translation.")
    return "Error in translation.", len(content), 0


def find_files(extensions, root_dir='.'):
    """Finds files recursively in the given directory that match any of the given extensions."""
    if isinstance(extensions, str):
        extensions = [extensions]
    logging.info(f"Recursively searching for files in '{root_dir}' matching extensions: {extensions}")
    found_files = []
    for root, _, files in os.walk(root_dir):
        for file_name in files:
            if any(file_name.lower().endswith(ext.lower()) for ext in extensions):
                full_path = os.path.join(root, file_name)
                found_files.append(full_path)
    return found_files

def read_pdf_pages(pdf_file, start_page=1, end_page=None):
    """Reads pages from a PDF file and returns the text of each page using pdfplumber."""
    logging.info("Opening PDF file: %s", pdf_file)
    try:
        with pdfplumber.open(pdf_file) as pdf:
            total_pages = len(pdf.pages)
            # Adjust end_page: if None, use total_pages; ensure it's not less than start_page
            end_page = end_page if end_page is not None else total_pages

            if start_page < 1:
                logging.warning("Start page must be 1 or greater. Adjusting to 1.")
                start_page = 1

            if start_page > end_page and end_page is not None:  # end_page could be 0 if total_pages is 0
                logging.warning(
                    "Invalid page range for PDF: Start page %d is greater than end page %d (Total pages: %d). No pages will be processed.",
                    start_page, end_page, total_pages
                )
                return

            if start_page > total_pages and total_pages > 0:
                logging.warning(
                    "Start page %d is greater than total pages %d. No pages will be processed.",
                    start_page, total_pages
                )
                return

            if total_pages == 0:
                logging.warning("PDF file %s has 0 pages.", pdf_file)
                return

            # Iterate from start_page-1 up to min(end_page, total_pages)
            for index in range(start_page - 1, min(end_page, total_pages)):
                logging.info("Reading page %d from PDF", index + 1)
                page = pdf.pages[index]
                text = page.extract_text(x_tolerance=1, y_tolerance=1) or ""  # Added tolerance for better extraction
                if not text.strip():
                    logging.warning("Page %d (PDF) contains no extractable text. Skipping...", index + 1)
                    continue
                yield index + 1, text
    except Exception as e:
        logging.error(f"Error reading PDF file {pdf_file}: {e}")
        return


def read_epub_pages(epub_file, start_item=1, end_item=None):
    """Reads content documents (items) from an EPUB file and returns the text of each item."""
    logging.info("Opening EPUB file: %s", epub_file)
    try:
        book = epub.read_epub(epub_file)
    except Exception as e:
        logging.error(f"Error opening or parsing EPUB file {epub_file}: {e}")
        return

    # Get all content documents (typically chapters or sections)
    content_items = [item for item in book.get_items_of_type(ITEM_DOCUMENT)]
    total_items = len(content_items)

    if total_items == 0:
        logging.warning("EPUB file %s contains no content documents.", epub_file)
        return

    # Adjust end_item: if None, use total_items
    end_item = end_item if end_item is not None else total_items

    if start_item < 1:
        logging.warning("Start item must be 1 or greater. Adjusting to 1.")
        start_item = 1

    if start_item > end_item:
        logging.warning(
            "Invalid item range for EPUB: Start item %d is greater than end item %d (Total items: %d). No items will be processed.",
            start_item, end_item, total_items
        )
        return

    if start_item > total_items:
        logging.warning(
            "Start item %d is greater than total items %d in EPUB. No items will be processed.",
            start_item, total_items
        )
        return

    # Iterate from start_item-1 up to min(end_item, total_items)
    # The user provides 1-based input, so adjust for 0-based indexing
    for index in range(start_item - 1, min(end_item, total_items)):
        item = content_items[index]
        item_number_for_user = index + 1  # This is the 1-based "page" number for output
        logging.info("Reading item %d from EPUB (content: %s)", item_number_for_user, item.get_name())
        try:
            # Decode content if it's bytes (common for EPUB items)
            html_content = item.get_content()
            if isinstance(html_content, bytes):
                html_content = html_content.decode('utf-8', errors='ignore')

            soup = BeautifulSoup(html_content, 'html.parser')

            # Extract text, joining paragraphs with newlines
            paragraphs = [p.get_text(strip=True) for p in
                          soup.find_all(['p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li'])]
            text = "\n".join(filter(None, paragraphs)) or ""  # Filter out empty strings

            if not text.strip():  # Check if text is empty after stripping whitespace
                logging.warning("Item %d (EPUB: %s) contains no extractable text. Skipping...", item_number_for_user,
                                item.get_name())
                continue
            yield item_number_for_user, text
        except Exception as e:
            logging.error(
                f"Error extracting text from item {item_number_for_user} ({item.get_name()}) in {epub_file}: {e}")
            continue


def create_target_document_stream(source_file, target_language, output_dir="output"):
    """Creates a target text document using a write stream and writes pages incrementally."""
    os.makedirs(output_dir, exist_ok=True)
    base_name = os.path.splitext(os.path.basename(source_file))[0]
    target_file = os.path.join(output_dir, f"{base_name}_{target_language}.txt")
    logging.info("Creating target document: %s", target_file)
    # Use 'w' to overwrite if exists, or 'a' to append. 'w' is safer for new runs.
    # If appending is desired for partial runs, change to 'a'.
    # For this script, 'w' makes more sense to avoid duplicate content on re-runs.
    # However, the original used 'a', so let's stick to that for incremental writes per file.
    # If processing multiple files, each gets its own new/appended file.
    return open(target_file, 'a', encoding='utf-8')


def write_page_to_document(file_stream, item_number, translated_text):
    """Writes a single item's (page/EPUB section) translated text to the target document."""
    file_stream.write(f"\n--- Page {item_number} ---\n\n")
    file_stream.write(translated_text.strip() + "\n")


def progress_file_path(output_file):
    return output_file.replace(".txt", ".progress.json")


def load_progress(output_file):
    path = progress_file_path(output_file)
    if not os.path.exists(path):
        return 0
    import json
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data.get("last_page", 0)


def save_progress(output_file, last_page, total_pages, language):
    import json
    path = progress_file_path(output_file)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({"last_page": last_page, "total_pages": total_pages, "language": language}, f, indent=2)


def throttle_request(last_request_time, min_interval=5):  # 5 seconds = 12 RPM (Free tier: 15 RPM)
    """Ensures a minimum interval between requests."""
    elapsed_time = time.time() - last_request_time
    if elapsed_time < min_interval:
        sleep_time = min_interval - elapsed_time
        logging.info("Throttling request for %.2f seconds.", sleep_time)
        time.sleep(sleep_time)


if __name__ == "__main__":
    import argparse
    
    # Set up command-line argument parsing
    parser = argparse.ArgumentParser(description='Translate documents using Google Gemini')
    parser.add_argument('--file', type=str, 
                      help='Path to a specific file or folder containing PDF/EPUB files to translate')
    parser.add_argument('--lang', type=str, default=LANGUAGE, 
                      help=f'Target language (e.g., "deutsch" for German, default: "{LANGUAGE}")')
    parser.add_argument('--range', type=str, default='',
                      help='Page/item range (e.g., "1-3", "5", or leave blank for all)')
    
    args = parser.parse_args()
    
    # Set language from command line or prompt
    if args.lang != LANGUAGE:
        LANGUAGE = args.lang.lower()
    else:
        user_lang_input = input(f"Enter the target language (e.g., 'deutsch' for German, default: '{LANGUAGE}'): ").strip()
        if user_lang_input:
            LANGUAGE = user_lang_input.lower()
    logging.info(f"Target language set to: {LANGUAGE}")
    
    # Set page range from command line or prompt
    range_input_str = args.range if args.range else input(
        "Enter the page/item range (e.g., '1-3', '5', or leave blank for all): "
    )
    start_processing_item, end_processing_item = 1, None  # Default: process all

    if "-" in range_input_str:
        try:
            start_str, end_str = range_input_str.split("-")
            start_processing_item = int(start_str)
            end_processing_item = int(end_str)
        except ValueError:
            logging.warning("Invalid range format. Defaulting to all pages/items.")
    elif range_input_str.isdigit():
        try:
            start_processing_item = int(range_input_str)
            end_processing_item = int(range_input_str)  # Process a single page/item
        except ValueError:
            logging.warning("Invalid page/item number. Defaulting to all pages/items.")

    logging.info(
        f"Processing range: Start item {start_processing_item}, End item {'All' if end_processing_item is None else end_processing_item}")

    supported_extensions = ['.pdf', '.epub']
    
    # If a specific file or folder was provided, use it; otherwise default to books/
    if args.file:
        if os.path.isfile(args.file):
            if not any(args.file.lower().endswith(ext) for ext in supported_extensions):
                logging.error(f"Unsupported file type. Please provide a PDF or EPUB file.")
                exit(1)
            source_files = [args.file]
        elif os.path.isdir(args.file):
            source_files = find_files(supported_extensions, args.file)
            if not source_files:
                logging.error(f"No PDF or EPUB files found in the specified directory: {args.file}")
                exit(1)
        else:
            logging.error(f"File or directory not found: {args.file}")
            exit(1)
    else:
        default_dir = "books"
        source_files = find_files(supported_extensions, default_dir)
        if not source_files:
            logging.warning(f"No PDF or EPUB files found in '{default_dir}/' with extensions: {supported_extensions}")
            exit(1)
        model = configure_genai()
        if not model:
            exit(1)  # API key or model configuration failed

        total_files = len(source_files)
        logging.info(f"Found {total_files} file(s) to process: {source_files}")

        for i, source_file in enumerate(source_files):
            logging.info(f"Processing file {i + 1}/{total_files}: {source_file}")

            # Determine target filename for logging completion
            base_name = os.path.splitext(os.path.basename(source_file))[0]
            target_output_filename = os.path.join("output", f"{base_name}_{LANGUAGE}.txt")

            # Auto-resume via progress file
            resume_from = load_progress(target_output_filename)
            file_start_item = max(start_processing_item, resume_from + 1)
            if resume_from > 0:
                logging.info(f"Resuming '{source_file}' from page {file_start_item} (last completed: {resume_from})")

            last_request_time = 0

            with create_target_document_stream(source_file, LANGUAGE) as target_stream:
                page_iterator = None
                file_type_processed = ""

                if source_file.lower().endswith('.pdf'):
                    page_iterator = read_pdf_pages(source_file, file_start_item, end_processing_item)
                    file_type_processed = "PDF"
                elif source_file.lower().endswith('.epub'):
                    page_iterator = read_epub_pages(source_file, file_start_item, end_processing_item)
                    file_type_processed = "EPUB"

                if not page_iterator:
                    logging.warning(f"Could not create a page/item iterator for {source_file}. Skipping.")
                    continue

                logging.info(f"Starting translation for {file_type_processed} file: {source_file}")
                processed_item_count = 0
                for item_number, item_text in page_iterator:
                    if not item_text.strip():  # Double check if iterator yielded empty text
                        logging.warning(
                            f"Item {item_number} from {source_file} has empty text after iterator. Skipping.")
                        continue

                    throttle_request(last_request_time)
                    last_request_time = time.time()

                    translated_text, original_chars, translated_chars = get_translation_with_genai(model, item_text)

                    if "Error in translation." in translated_text and translated_chars == 0:
                        logging.error(f"Failed to translate item {item_number} from {source_file}.")
                    else:
                        logging.info(
                            "Item %d (%s): Original characters: %d, Translated characters: %d",
                            item_number, file_type_processed, original_chars, translated_chars
                        )
                        write_page_to_document(target_stream, item_number, translated_text)
                        target_stream.flush()
                        save_progress(target_output_filename, item_number, end_processing_item or 0, LANGUAGE)
                        processed_item_count += 1

                if processed_item_count == 0:
                    logging.warning(
                        f"No items were processed for {source_file} within the specified range or due to empty content.")

            logging.info(
                f"Translation processing completed for {source_file}. Results saved in: {target_output_filename}")

        logging.info("All files processed.")