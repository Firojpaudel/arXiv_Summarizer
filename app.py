import os
import re
from flask import Flask, render_template, request
from werkzeug.utils import secure_filename
import fitz  # PyMuPDF for PDF handling
import requests
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
import nltk
from nltk.corpus import stopwords
import markdown



# Download required NLTK resources
nltk.download('stopwords')
nltk.download('punkt')

# Initialize stopwords
stop_words = set(stopwords.words('english'))

app = Flask(__name__)

# Allowed file extensions
ALLOWED_EXTENSIONS = {'txt', 'pdf'}

# Path to save uploaded files temporarily
UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Initialize the models and tokenizers
bart_model_path = "fine_tuned_bart"
t5_model_path = "t5-base"

bart_model = AutoModelForSeq2SeqLM.from_pretrained(bart_model_path)
bart_tokenizer = AutoTokenizer.from_pretrained(bart_model_path)

t5_model = AutoModelForSeq2SeqLM.from_pretrained(t5_model_path)
t5_tokenizer = AutoTokenizer.from_pretrained(t5_model_path)

# Check if the file extension is allowed
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Download PDF from a URL
def download_pdf_from_url(url):
    try:
        response = requests.get(url, stream=True)
        if response.status_code == 200:
            pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], "downloaded_temp.pdf")
            with open(pdf_path, "wb") as f:
                f.write(response.content)
            return pdf_path
        else:
            return f"Error: Failed to download PDF. HTTP Status Code: {response.status_code}"
    except Exception as e:
        return f"Error downloading PDF from URL: {str(e)}"

# Extract text from a PDF file
def extract_text_from_pdf(pdf_path):
    try:
        doc = fitz.open(pdf_path)
        text = ""
        for page in doc:
            text += page.get_text("text")
        return text
    except Exception as e:
        return f"Error extracting text from PDF: {str(e)}"

# Extract text from a TXT file
def extract_text_from_txt(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            text = file.read()
        return text
    except Exception as e:
        return f"Error extracting text from TXT file: {str(e)}"

# Clean text for model input
def clean_text(text):
    text = re.sub(r'\s*#\s*\d+\s*', '', text)  # Remove patterns like '# # 1 # 2 # 3'
    text = re.sub(r'\b\d+\b', '', text)  # Remove stray numbers
    text = text.replace("- ", "")  # Remove hyphenated breaks
    text = re.sub(r'\s+', ' ', text)  # Remove extra spaces
    return text.strip()

# Summarize text with BART
def summarize_with_bart(text):
    try:
        inputs = bart_tokenizer(text, return_tensors="pt", max_length=1024, truncation=True)
        summary_ids = bart_model.generate(
            inputs['input_ids'], max_length=500, min_length=300, num_beams=4, early_stopping=True
        )
        summary = bart_tokenizer.decode(summary_ids[0], skip_special_tokens=True)
        return summary
    except Exception as e:
        return f"Error summarizing with BART: {str(e)}"

# Elaborate text with T5
def elaborate_with_t5(bart_summary, title=None):
    try:
        # Include title in the elaboration prompt if available
        input_prompt = f"elaborate: {bart_summary} (Title: {title})" if title else f"elaborate: {bart_summary}"

        inputs = t5_tokenizer(input_prompt, return_tensors="pt", max_length=512, truncation=True)
        elaboration_ids = t5_model.generate(
            inputs['input_ids'], max_length=1000, min_length=700, num_beams=5, early_stopping=True
        )
        elaboration = t5_tokenizer.decode(elaboration_ids[0], skip_special_tokens=True)

        # Ensure at least two paragraphs
        elaboration = re.sub(r'([.!?])\s*(?=\S)', r'\1\n\n', elaboration.strip())
        paragraphs = elaboration.split("\n\n")
        if len(paragraphs) < 2:
            paragraphs = [elaboration[:len(elaboration)//2].strip(), elaboration[len(elaboration)//2:].strip()]

        # Format the elaboration with the title
        if title:
            formatted_elaboration = f"#### Summary of \"{title}\...\" paper\n***\n" + "\n".join(paragraphs)
        else:
            formatted_elaboration = "\n\n".join(paragraphs)

        return formatted_elaboration.strip()
    except Exception as e:
        return f"Error elaborating with T5: {str(e)}"

# Extract title from text (assumes title is in the first line or the first few lines)
def extract_title_from_text(text):
    lines = text.split("\n")
    title = lines[0] if lines else "Untitled Paper"
    return title.strip()

# Process input text through summarization and elaboration
def process_text(text):
    cleaned_text = clean_text(text)
    bart_summary = summarize_with_bart(cleaned_text)
    if "Error" in bart_summary:
        return bart_summary
    title = extract_title_from_text(text)  # Extract title here
    t5_elaboration = elaborate_with_t5(bart_summary, title)
    return t5_elaboration

# Home route
@app.route('/')
def home():
    return render_template('index.html')

# Summary route
@app.route('/summary', methods=['GET', 'POST'])
def summary():
    result = None
    error_message = None

    if request.method == 'POST':
        try:
            input_text = request.form.get('text')
            file = request.files.get('file')
            url = request.form.get('url')

            if input_text:
                result = process_text(input_text)
            elif file and allowed_file(file.filename):
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(file.filename))
                file.save(file_path)
                if file.filename.endswith('.pdf'):
                    text = extract_text_from_pdf(file_path)
                else:
                    text = extract_text_from_txt(file_path)
                result = process_text(text)
            elif url:
                pdf_path = download_pdf_from_url(url)
                if "Error" not in pdf_path:
                    text = extract_text_from_pdf(pdf_path)
                    result = process_text(text)
                else:
                    result = pdf_path
            else:
                error_message = "No valid input provided. Please enter text, upload a file, or provide a URL."

            # Convert the resulting Markdown into HTML
            if result:
                result = markdown.markdown(result)

        except Exception as e:
            error_message = f"An error occurred: {str(e)}"

    return render_template('summarize.html', summary=result, error=error_message)

if __name__ == '__main__':
    app.run(debug=True)
