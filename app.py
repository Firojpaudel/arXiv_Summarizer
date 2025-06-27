import os
import re
import json
from time import sleep
import backoff
from flask import Flask, render_template, request, jsonify
from werkzeug.utils import secure_filename
import requests
import google.generativeai as genai
import markdown
import logging
from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError
import arxiv
import PyPDF2

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Allowed file extensions
ALLOWED_EXTENSIONS = {'txt', 'pdf'}

# Path to save uploaded files temporarily
UPLOAD_FOLDER = 'Uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Configure Gemini API
genai.configure(api_key=os.getenv('GEMINI_API_KEY'))
gemini_model = genai.GenerativeModel('gemini-2.0-flash')

# Pydantic model for structured PDF extraction
class PaperContent(BaseModel):
    title: str = Field(default="Untitled Paper", description="The title of the paper")
    abstract: str = Field(default="", description="The abstract of the paper")
    body: str = Field(default="", description="The main body text of the paper, excluding references")

# Pydantic model for structured summary
class SummaryOutput(BaseModel):
    title: str = Field(default="Untitled Paper", description="The title of the paper")
    summary: str = Field(default="", description="A concise summary of the paper in 3-4 paragraphs")
    keywords: list[str] = Field(default=["research", "paper", "summary"], description="A list of 5-7 relevant keywords")

def allowed_file(filename):
    """Check if file extension is allowed."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def download_pdf_from_url(url, retries=3):
    """Download PDF from a URL with retries, handling 304 and timeouts."""
    @backoff.on_exception(backoff.expo, requests.exceptions.RequestException, max_tries=retries)
    def download():
        response = requests.get(url, stream=True, timeout=10, headers={'Cache-Control': 'no-cache'})
        response.raise_for_status()
        pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], "downloaded_temp.pdf")
        with open(pdf_path, "wb") as f:
            f.write(response.content)
        logger.info(f"Downloaded PDF from {url} to {pdf_path}")
        return pdf_path

    try:
        return download()
    except requests.exceptions.HTTPError as e:
        logger.warning(f"HTTP error downloading PDF from {url}: {str(e)}")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to download PDF from {url} after {retries} attempts: {str(e)}")
        return None

def extract_arxiv_abstract(url):
    """Fetch abstract from arXiv URL as fallback."""
    try:
        arxiv_id = re.search(r'(\d+\.\d+[vV]\d*)', url)
        if not arxiv_id:
            logger.warning("No arXiv ID found in URL")
            return None
        search = arxiv.Search(id_list=[arxiv_id.group(1)])
        paper = next(search.results())
        logger.info(f"Extracted arXiv abstract for ID: {arxiv_id.group(1)}")
        return paper.title + "\n\n" + paper.summary
    except Exception as e:
        logger.error(f"Error fetching arXiv abstract: {str(e)}")
        return None

def fix_latex_escapes(text):
    """Preprocess Gemini response to ensure inline equations use $...$ and preserve LaTeX commands."""
    # Store display and inline equations to preserve them
    equations = []
    def store_equation(match):
        equations.append(match.group(0))
        return f"__EQUATION_{len(equations)-1}__"
    
    # Preserve existing $...$ and $$...$$ equations
    text = re.sub(r'\$\$[\s\S]*?\$\$', store_equation, text)
    text = re.sub(r'\$[\s\S]*?\$', store_equation, text)
    
    # Convert other LaTeX math delimiters to $...$ for inline rendering
    text = re.sub(r'\\\((.*?)\\\)', r'$\1$', text)
    text = re.sub(r'\\\[([\s\S]*?)\\\]', r'$$\1$$', text)  # Preserve display math
    text = re.sub(r'\\begin\{equation\}([\s\S]*?)\\end\{equation\}', r'$$\1$$', text)
    
    # Fix common LaTeX artifacts (e.g., //sqrt, double backslashes)
    text = re.sub(r'//([a-zA-Z]+)', r'\\\1', text)  # Convert //sqrt to \sqrt
    text = re.sub(r'\\{2,}', r'\\', text)  # Replace multiple backslashes with single
    text = re.sub(r'\\([a-zA-Z]+)\s*\{', r'\\\1{', text)  # Ensure no space between command and brace
    text = re.sub(r'\\([a-zA-Z]+)\s*([^\{])', r'\\\1 \2', text)  # Ensure space after command if not followed by brace
    
    # Ensure LaTeX commands like \frac are properly formatted
    text = re.sub(r'\\frac\s*([^ \{][^\{]*?)\s*([^ \}]*)', r'\\frac{\1}{\2}', text)
    
    # Escape single backslashes for JSON compatibility, excluding equations
    parts = []
    current_pos = 0
    for match in re.finditer(r'__EQUATION_\d+__', text):
        start, end = match.span()
        before = text[current_pos:start]
        before = re.sub(r'(?<!\\)\\([^\n$])', r'\\\\\1', before)  # Escape backslashes outside equations
        parts.append(before)
        parts.append(match.group(0))
        current_pos = end
    remaining = text[current_pos:]
    remaining = re.sub(r'(?<!\\)\\([^\n$])', r'\\\\\1', remaining)
    parts.append(remaining)
    text = ''.join(parts)
    
    # Restore equations
    for i, eq in enumerate(equations):
        text = text.replace(f"__EQUATION_{i}__", eq)
    
    return text

def parse_plain_text_response(text):
    """Parse plain text response to extract title, summary/body, and keywords."""
    lines = text.split('\n')
    content = {'title': 'Untitled Paper', 'summary': '', 'keywords': ['research', 'paper', 'summary']}
    current_field = None
    summary_lines = []
    
    for line in lines:
        line = line.strip()
        if line.startswith('Title:'):
            content['title'] = line[len('Title:'):].strip()
        elif line.startswith('Abstract:') or line.startswith('Summary:'):
            current_field = 'summary'
            summary_lines.append(line[len('Abstract:') or len('Summary:'):].strip())
        elif line.startswith('Keywords:'):
            current_field = 'keywords'
            content['keywords'] = [k.strip() for k in line[len('Keywords:'):].split(',')]
        elif current_field == 'summary' and line:
            summary_lines.append(line)
        elif current_field == 'keywords' and line:
            content['keywords'].extend([k.strip() for k in line.split(',')])
    
    content['summary'] = ' '.join(summary_lines).strip()
    if 'body' in content:
        content['summary'] = content['body']
    return content

def merge_summary_fields(content):
    """Merge multiple 'summary' fields in JSON response into a single string."""
    if 'summary' in content:
        if isinstance(content['summary'], list):
            content['summary'] = '\n\n'.join(str(s) for s in content['summary'] if s)
        elif isinstance(content['summary'], dict):
            content['summary'] = str(content['summary'])
        elif not isinstance(content['summary'], str):
            content['summary'] = str(content['summary'])
    return content

def extract_text_from_pdf_local(pdf_path):
    """Extract text from PDF using PyPDF2 as a local fallback with LaTeX cleanup."""
    try:
        logger.info(f"Performing local extraction on: {pdf_path}")
        with open(pdf_path, 'rb') as file:
            reader = PyPDF2.PdfReader(file)
            text = ""
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
            if not text.strip():
                return "Error: No text extracted from PDF. The PDF may be scanned or encrypted."
            text = clean_text(text)
            logger.info(f"Local extraction text length: {len(text)} characters")
            return text
    except Exception as e:
        logger.error(f"Local extraction failed: {str(e)}")
        return f"Error extracting text from PDF locally: {str(e)}"

def extract_text_from_pdf(pdf_path, retries=5):
    """Extract structured text from PDF using Gemini API with retries, falling back to local extraction."""
    @backoff.on_exception(backoff.expo, Exception, max_tries=retries)
    def extract():
        logger.info(f"Attempting to upload file: {pdf_path}")
        logger.info(f"File size: {os.path.getsize(pdf_path)} bytes")
        sample_file = genai.upload_file(path=pdf_path, display_name="arXiv_paper")
        logger.info(f"Successfully uploaded file '{sample_file.display_name}' as: {sample_file.uri}")

        prompt = (
            "Extract the title, abstract, and main body text (excluding references, headers, footers, page numbers, "
            "and LaTeX artifacts) from the provided PDF. Format all mathematical equations in LaTeX using $...$ "
            "delimiters for inline math (e.g., $E = mc^2$) and $$...$$ for display math. Strictly avoid using \\(...\\), "
            "\\[...\\], or \\begin{equation}...\\end{equation}. Ensure all LaTeX commands (e.g., \\sqrt, \\frac) use a "
            "single backslash and are properly formatted. Return the output in JSON format with fields: title, abstract, body."
        )
        logger.info("Sending request to Gemini API for PDF extraction")
        response = gemini_model.generate_content(
            [prompt, sample_file],
            generation_config={"response_mime_type": "application/json"},
            request_options={"timeout": 120}
        )
        
        logger.debug(f"Gemini raw response: {response.text}")

        fixed_response = fix_latex_escapes(response.text)
        content = json.loads(fixed_response)
        content = merge_summary_fields(content)
        return content

    try:
        content = extract()
        try:
            paper_content = PaperContent(**content)
        except ValidationError as e:
            logger.warning(f"Pydantic validation error: {str(e)}")
            content.setdefault('title', 'Untitled Paper')
            content.setdefault('abstract', '')
            content.setdefault('body', '')
            paper_content = PaperContent(**content)

        full_text = f"{paper_content.title}\n\n{paper_content.abstract}\n\n{paper_content.body}"
        logger.info(f"Extracted text length: {len(full_text)} characters")
        return full_text
    except json.JSONDecodeError as e:
        logger.warning(f"Invalid JSON response: {str(e)}")
        logger.info("Falling back to local extraction")
        return extract_text_from_pdf_local(pdf_path)
    except Exception as e:
        logger.error(f"Failed to extract text with Gemini: {str(e)}")
        return extract_text_from_pdf_local(pdf_path)

def extract_text_from_txt(file_path):
    """Extract text from a TXT file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            text = file.read()
        text = clean_text(text)
        logger.info(f"Extracted text length from TXT: {len(text)} characters")
        return text
    except Exception as e:
        logger.error(f"Error extracting text from TXT: {str(e)}")
        return f"Error extracting text from TXT file: {str(e)}"

def clean_text(text):
    """Clean text by removing residual LaTeX and metadata, preserving equations."""
    equations = []
    def store_equation(match):
        equations.append(match.group(0))
        return f"__EQUATION_{len(equations)-1}__"
    
    text = re.sub(r'\$\$[\s\S]*?\$\$', store_equation, text)
    text = re.sub(r'\$[\s\S]*?\$', store_equation, text)
    
    text = re.sub(r'//([a-zA-Z]+)', r'\\\1', text)
    text = re.sub(r'\\{2,}', r'\\', text)
    text = re.sub(r'\\begin\{[^}]*\}[\s\S]*?\\end\{[^}]*\}', '', text)
    text = re.sub(r'\\([a-zA-Z]+)\s*\{', r'\\\1{', text)
    text = re.sub(r'\\([a-zA-Z]+)\s*([^\{])', r'\\\1 \2', text)
    text = re.sub(r'\\[a-zA-Z]+{[^}]*}', '', text)
    text = re.sub(r'\{|\}', '', text)
    text = re.sub(r'arXiv:\d+\.\d+[vV]\d*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[\s*[a-zA-Z]+\.\w+\s*\]', '', text)
    text = re.sub(r'\bpacs\s*number\(s\)\s*:[^\n]*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\b\d+\.\d+\.\w+\b', '', text)
    text = text.replace("- ", "").replace("-\n", "")
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'\n+', '\n', text)
    
    for i, eq in enumerate(equations):
        text = text.replace(f"__EQUATION_{i}__", eq)
    
    return text.strip()

def summarize_with_gemini(text, retries=5):
    """Generate a summary using Gemini API with retries."""
    @backoff.on_exception(backoff.expo, Exception, max_tries=retries)
    def summarize():
        prompt = (
            "You are an expert research assistant. Carefully read the provided document. "
            "Generate a concise, professional summary in 3-4 paragraphs, focusing on main ideas, "
            "methodology, results, and contributions. Format all mathematical equations in LaTeX using "
            "$...$ delimiters for inline math (e.g., $E = mc^2$) and $$...$$ for display math. Strictly "
            "avoid using \\(...\\), \\[...\\], or \\begin{equation}...\\end{equation}. Ensure all LaTeX "
            "commands (e.g., \\sqrt, \\frac) use a single backslash and are properly formatted. Return "
            "the output in JSON format with fields: title, summary (single string), keywords."
        )
        logger.info("Sending request to Gemini API for summarization")
        response = gemini_model.generate_content(
            [prompt, text],
            generation_config={"response_mime_type": "application/json"},
            request_options={"timeout": 120}
        )
        
        logger.debug(f"Gemini summary raw response: {response.text}")

        fixed_response = fix_latex_escapes(response.text)
        content = json.loads(fixed_response)
        content = merge_summary_fields(content)
        return content

    try:
        content = summarize()
        try:
            summary_output = SummaryOutput(**content)
        except ValidationError as e:
            logger.warning(f"Pydantic validation error: {str(e)}")
            content.setdefault('title', 'Untitled Paper')
            content.setdefault('summary', 'Summary could not be generated due to incomplete data.')
            content.setdefault('keywords', ['research', 'paper', 'summary'])
            summary_output = SummaryOutput(**content)

        formatted_summary = (
            f"## Summary of \"{summary_output.title}...\"\n\n"
            f"{summary_output.summary}\n\n"
            f"**Keywords**: {', '.join(summary_output.keywords)}"
        )
        logger.info(f"Generated summary length: {len(formatted_summary)} characters")
        return formatted_summary
    except json.JSONDecodeError as e:
        logger.warning(f"Invalid JSON response: {str(e)}")
        logger.info("Falling back to plain text summarization")
        return fallback_summarize_text(text)
    except Exception as e:
        logger.error(f"Failed to summarize after {retries} attempts: {str(e)}")
        return fallback_summarize_text(text)

def fallback_summarize_text(text):
    """Fallback to plain text summarization if JSON parsing fails."""
    try:
        prompt = (
            "You are an expert research assistant. Carefully read the provided document. "
            "Generate a concise, professional summary in 3-4 paragraphs, focusing on main ideas, "
            "methodology, results, and contributions. Format all mathematical equations in LaTeX using "
            "$...$ delimiters for inline math (e.g., $E = mc^2$) and $$...$$ for display math. Strictly "
            "avoid using \\(...\\), \\[...\\], or \\begin{equation}...\\end{equation}. Ensure all LaTeX "
            "commands (e.g., \\sqrt, \\frac) use a single backslash and are properly formatted. Return "
            "the output as plain text with sections labeled as 'Title:', 'Summary:', and 'Keywords:'."
        )
        logger.info("Sending request to Gemini API for fallback summarization")
        response = gemini_model.generate_content(
            [prompt, text],
            generation_config={"response_mime_type": "text/plain"},
            request_options={"timeout": 120}
        )
        content = parse_plain_text_response(response.text)
        formatted_summary = (
            f"## Summary of \"{content['title']}...\"\n\n"
            f"{content['summary']}\n\n"
            f"**Keywords**: {', '.join(content['keywords'])}"
        )
        logger.info(f"Fallback summary length: {len(formatted_summary)} characters")
        return formatted_summary
    except Exception as e:
        logger.error(f"Fallback summarization failed: {str(e)}")
        return f"Error summarizing with Gemini: {str(e)}"

def process_text(text, url=None):
    """Process text through cleaning and Gemini summarization."""
    cleaned_text = clean_text(text)
    summary = summarize_with_gemini(cleaned_text)
    if "Error" in summary and url:
        arxiv_text = extract_arxiv_abstract(url)
        if arxiv_text:
            logger.info("Using arXiv API fallback for summarization")
            return summarize_with_gemini(clean_text(arxiv_text))
    return summary

@app.route('/')
def home():
    """Render home page."""
    return render_template('index.html')

@app.route('/summary', methods=['GET', 'POST'])
def summary():
    """Handle summary generation."""
    result = None
    error_message = None

    if request.method == 'POST':
        try:
            input_text = request.form.get('text')
            file = request.files.get('file')
            url = request.form.get('url')

            if file and allowed_file(file.filename):
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(file.filename))
                file.save(file_path)
                if file.filename.endswith('.pdf'):
                    text = extract_text_from_pdf(file_path)
                else:
                    text = extract_text_from_txt(file_path)
                result = process_text(text, None)
            elif input_text:
                result = process_text(input_text, url)
            elif url:
                pdf_path = download_pdf_from_url(url)
                if pdf_path:
                    text = extract_text_from_pdf(pdf_path)
                    result = process_text(text, url)
                else:
                    arxiv_text = extract_arxiv_abstract(url)
                    if arxiv_text:
                        result = process_text(arxiv_text, url)
                    else:
                        error_message = "Failed to download PDF and fetch arXiv abstract due to network issues. Please upload the PDF manually."
            else:
                error_message = "No valid input provided. Please enter text, upload a file, or provide a URL."

            if result and "Error" not in result:
                result = markdown.markdown(result, extensions=['nl2br', 'fenced_code', 'tables'])

        except Exception as e:
            logger.error(f"Error in summary route: {str(e)}")
            error_message = f"An error occurred: {str(e)}"

        return jsonify({
            'summary': result,
            'error': error_message
        })

    return render_template('summarize.html', summary=result, error=error_message)

if __name__ == '__main__':
    app.run(debug=True)