import os
from flask import Flask, render_template, request, redirect, url_for
from werkzeug.utils import secure_filename
import fitz  # PyMuPDF for PDF handling
import requests
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
import re
import pytesseract
from PIL import Image

app = Flask(__name__)

ALLOWED_EXTENSIONS = {'txt', 'pdf'}

# Path to save uploaded files temporarily
UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Initialize the model and tokenizer
model_path = "fine_tuned_bart"
model = AutoModelForSeq2SeqLM.from_pretrained(model_path)
tokenizer = AutoTokenizer.from_pretrained(model_path)

# Check if the file extension is allowed
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Extract text from a PDF file
def extract_text_from_pdf(pdf_path):
    doc = fitz.open(pdf_path)
    text = ""
    for page in doc:
        text += page.get_text("text")
    return text

# Extract text from a TXT file
def extract_text_from_txt(txt_path):
    with open(txt_path, 'r') as file:
        return file.read()

# Download PDF from a URL and save locally
def download_pdf_from_url(url):
    response = requests.get(url)
    if response.status_code == 200:
        with open("temp.pdf", "wb") as f:
            f.write(response.content)
        return "temp.pdf"
    else:
        raise Exception("Failed to download PDF from the URL.")

# Clean unwanted parts (e.g., page numbers, footnotes)
def clean_text(text):
    text = re.sub(r'\[\d+\]', '', text)
    text = re.sub(r'(\d+(\.\d+)*)\s+', '', text)  # Removing page number patterns
    text = re.sub(r'\s+', ' ', text).strip()  # Reducing excessive whitespace
    return text

# Split text by headings (e.g., 1., 1.1, 1.2.1, etc.)
def split_by_headings(text):
    # Improved regex to handle headings more robustly (supports 1., 1.1, 1.2.1, etc.)
    headings = re.split(r'(\d+(\.\d+)*\s+[^\n]+)', text)
    sections = []
    
    # Debug output to check what's being matched
    print("Debugging split: ", headings)

    # Check if the split headings are in the correct order and handle missing parts
    for i in range(1, len(headings) - 1, 2):
        section_title = headings[i].strip() if headings[i] else ""
        section_text = headings[i + 1].strip() if (i + 1 < len(headings) and headings[i + 1]) else ""

        # Only append non-empty sections
        if section_title and section_text:
            sections.append((section_title, section_text))

    return sections

# Preserve formulas in LaTeX style and remove unnecessary parts
def clean_text_with_formulas(text):
    text = re.sub(r'(\$.*?\$)', r'<math>\1</math>', text)  # Inline math
    text = re.sub(r'\\\[.*?\\\]', r'<math>\1</math>', text)  # Display math
    text = re.sub(r'\[\d+\]', '', text)  # Remove references like [1], [2], etc.
    text = re.sub(r'(\d+(\.\d+)*)\s+', '', text)  # Remove page number patterns
    text = re.sub(r'\s+', ' ', text).strip()  # Reduce excessive whitespace
    return text

# Summarize each section
def summarize_section(section_text):
    try:
        cleaned_section = clean_text_with_formulas(section_text)
        inputs = tokenizer(cleaned_section, return_tensors="pt", max_length=1024, truncation=True)
        summary_ids = model.generate(inputs['input_ids'], max_length=150, min_length=50, length_penalty=2.0, num_beams=4, early_stopping=True)
        summary = tokenizer.decode(summary_ids[0], skip_special_tokens=True).replace("\n", "")
        return summary
    except Exception as e:
        return f"An error occurred: {str(e)}"

# Summarize the entire document
def summarize_document(text):
    sections = split_by_headings(text)
    summaries = {}
    for title, section_text in sections:
        if section_text:
            section_summary = summarize_section(section_text)
            summaries[title] = section_summary
    return summaries

# Extract formula from image using OCR
def extract_formula_from_image(image_path):
    try:
        img = Image.open(image_path)
        formula_text = pytesseract.image_to_string(img, config='--psm 6')
        return formula_text
    except Exception as e:
        return f"Error extracting text from image: {str(e)}"

# Home route
@app.route('/')
def home():
    return render_template('index.html')

# Summary route (handles text input, file uploads, and URL inputs)
@app.route('/summary', methods=['GET', 'POST'])
def summary():
    summary = None
    if request.method == 'POST':
        input_text = request.form.get('text')
        if input_text:
            summary = summarize_section(input_text)
        
        file = request.files.get('file')
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            
            # Extract text based on file type
            if filename.endswith('.pdf'):
                text = extract_text_from_pdf(file_path)
            else:
                text = extract_text_from_txt(file_path)

            # Handle images (OCR) for PDF
            if filename.endswith('.pdf'):
                doc = fitz.open(file_path)
                for page in doc:
                    images = page.get_images(full=True)
                    for img in images:
                        xref = img[0]
                        base_image = doc.extract_image(xref)
                        image_bytes = base_image["image"]
                        image_path = os.path.join(app.config['UPLOAD_FOLDER'], f"image_{xref}.png")
                        with open(image_path, 'wb') as img_file:
                            img_file.write(image_bytes)
                        formula = extract_formula_from_image(image_path)
                        if formula:
                            text += "\n" + formula

            # Generate summary by section
            summary = summarize_document(text)
        
        # Handle URL input
        url = request.form.get('url')
        if url:
            try:
                pdf_path = download_pdf_from_url(url)
                text = extract_text_from_pdf(pdf_path)
                summary = summarize_document(text)
            except Exception as e:
                summary = f"An error occurred: {str(e)}"

    return render_template('summarize.html', summary=summary)

# Summarize page route
@app.route('/summarize')
def summarize_page():
    return render_template('summarize.html')

if __name__ == '__main__':
    app.run(debug=True)


