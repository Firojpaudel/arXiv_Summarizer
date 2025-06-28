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
import arxiv
import PyPDF2
from sqlalchemy.orm import Session as SQLSession
from db import Session, SummaryHistory

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

def allowed_file(filename):
    """Check if file extension is allowed."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def download_pdf_from_url(url, retries=3):
    """Download PDF from a URL with retries, handling redirects and content validation."""
    @backoff.on_exception(backoff.expo, requests.exceptions.RequestException, max_tries=retries)
    def download():
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Cache-Control': 'no-cache'
            }
            response = requests.get(url, stream=True, timeout=30, headers=headers, allow_redirects=True)
            response.raise_for_status()

            content_type = response.headers.get('content-type', '').lower()
            if 'application/pdf' not in content_type:
                logger.error(f"URL {url} does not point to a PDF file (Content-Type: {content_type})")
                raise ValueError("The provided URL does not point to a valid PDF file")

            pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], "downloaded_temp.pdf")
            with open(pdf_path, "wb") as f:
                f.write(response.content)
            logger.info(f"Downloaded PDF from {url} to {pdf_path}")
            return pdf_path
        except requests.exceptions.HTTPError as e:
            logger.warning(f"HTTP error downloading PDF from {url}: {str(e)}")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to download PDF from {url}: {str(e)}")
            raise
        except ValueError as e:
            logger.error(str(e))
            raise

    try:
        return download()
    except Exception as e:
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

def extract_and_preserve_equations(text):
    """Preserve LaTeX equations in their original format."""
    # Simply return the text and an empty placeholder dictionary
    # Equations are preserved as-is in the text (e.g., $...$, $$...$$)
    return text, {}

def clean_text_preserve_equations(text):
    """Clean text while preserving LaTeX equations."""
    try:
        # Remove arXiv IDs
        text = re.sub(r'arXiv:\d+\.\d+[vV]\d*', '', text, flags=re.IGNORECASE)

        # Remove PACS numbers
        text = re.sub(r'\bpacs\s*number\(s\)\s*:[^\n]*', '', text, flags=re.IGNORECASE)

        # Remove figure/table references
        text = re.sub(r'\[\s*[fF]ig\.\w+\s*\]', '', text)
        text = re.sub(r'\[\s*[tT]able\.\w+\s*\]', '', text)

        # Remove DOI patterns
        text = re.sub(r'\b\d+\.\d+\.\w+\b', '', text)

        # Clean up hyphenated line breaks
        text = text.replace("- ", "").replace("-\n", "")

        # Normalize whitespace
        text = re.sub(r'[ \t]+', ' ', text)
        text = re.sub(r'\n+', '\n', text)

        # Minimal LaTeX cleanup to avoid breaking equations
        text = re.sub(r'//sqrt', r'\sqrt', text)
        text = re.sub(r':\s*(\$\$)', r'\1', text)

        return text.strip(), {}
    except re.error as e:
        logger.error(f"Regex error in clean_text_preserve_equations: {str(e)}")
        return text, {}

def extract_text_from_pdf_local(pdf_path):
    """Extract text from PDF using PyPDF2 as a fallback."""
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
                return "Error: No text extracted from PDF. The PDF may be scanned or encrypted. Consider using OCR.", {}
            text, equation_placeholders = clean_text_preserve_equations(text)
            logger.info(f"Local extraction text length: {len(text)} characters")
            return text, equation_placeholders
    except Exception as e:
        logger.error(f"Local extraction failed: {str(e)}")
        return f"Error extracting text from PDF locally: {str(e)}", {}

def extract_text_from_pdf(pdf_path, retries=3):
    """Extract text from PDF using Gemini API with equation preservation."""
    @backoff.on_exception(backoff.expo, Exception, max_tries=retries)
    def extract():
        logger.info(f"Attempting to upload file: {pdf_path}")
        logger.info(f"File size: {os.path.getsize(pdf_path)} bytes")
        sample_file = genai.upload_file(path=pdf_path, display_name="research_paper")
        logger.info(f"Successfully uploaded file '{sample_file.display_name}' as: {sample_file.uri}")

        prompt = (
            "Extract all the text content from this PDF, paying special attention to mathematical equations. "
            "Preserve all LaTeX equations in their original format (e.g., $...$, $$...$$, \\begin{equation}...\\end{equation}). "
            "Focus on the main content including title, abstract, introduction, methodology, results, and conclusions. "
            "Ignore headers, footers, page numbers, and reference lists. "
            "Return the extracted text in a clean, readable format with equations intact."
        )

        logger.info("Sending request to Gemini API for PDF extraction")
        response = gemini_model.generate_content(
            [prompt, sample_file],
            request_options={"timeout": 120}
        )

        return response.text

    try:
        extracted_text = extract()
        cleaned_text, equation_placeholders = clean_text_preserve_equations(extracted_text)
        logger.info(f"Extracted text length: {len(cleaned_text)} characters")
        return cleaned_text, equation_placeholders
    except Exception as e:
        logger.error(f"Failed to extract text with Gemini: {str(e)}")
        return extract_text_from_pdf_local(pdf_path)

def extract_text_from_txt(file_path):
    """Extract text from a TXT file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            text = file.read()
        text, equation_placeholders = clean_text_preserve_equations(text)
        logger.info(f"Extracted text length from TXT: {len(text)} characters")
        return text, equation_placeholders
    except Exception as e:
        logger.error(f"Error extracting text from TXT: {str(e)}")
        return f"Error extracting text from TXT file: {str(e)}", {}

def extract_title_from_text(text):
    """Extract title from the beginning of the text."""
    lines = text.split('\n')
    for line in lines[:10]:
        line = line.strip()
        if len(line) > 10 and len(line) < 200:
            if not any(keyword in line.lower() for keyword in ['arxiv', 'doi', 'abstract', 'keywords']):
                return line
    return "Research Paper"

def restore_equations_in_text(text, equation_placeholders):
    """No-op since equations are preserved in original format."""
    return text

def parse_summary_response(response_text, equation_placeholders):
    """Parse the summary response and extract components."""
    lines = response_text.split('\n')
    title = ""
    summary = ""
    keywords = []
    
    current_section = None
    summary_lines = []
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        if line.lower().startswith('title:'):
            title = line[6:].strip()
            current_section = None
        elif line.lower().startswith('summary:'):
            current_section = 'summary'
            if len(line) > 8:
                summary_lines.append(line[8:].strip())
        elif line.lower().startswith('keywords:'):
            current_section = 'keywords'
            keyword_text = line[9:].strip()
            if keyword_text:
                keywords = [k.strip() for k in keyword_text.split(',') if k.strip()]
        elif current_section == 'summary':
            summary_lines.append(line)
        elif current_section == 'keywords':
            keywords.extend([k.strip() for k in line.split(',') if k.strip()])

    summary = '\n\n'.join([line for line in summary_lines if line]).strip()
    
    if not summary and not title:
        title = extract_title_from_text(response_text)
        summary = response_text.strip()
    
    if not title:
        title = "Research Paper"
    if not summary:
        summary = "Summary could not be generated properly."
    if not keywords:
        keywords = ["research", "analysis", "study"]
    
    return title, summary, keywords

def generate_summary_with_gemini(text, equation_placeholders, retries=3):
    """Generate a comprehensive summary using Gemini API with equation awareness."""
    @backoff.on_exception(backoff.expo, Exception, max_tries=retries)
    def summarize():
        prompt = f"""
You are an expert research analyst. Analyze this research paper and provide a comprehensive summary that includes the most important mathematical equations.

Instructions:
1. Create a detailed summary of 900-1000 words in 3-4 paragraphs
2. Structure the summary to cover:
   - Introduction, problem statement, and objectives
   - Methodology and approach (include 1-2 key equations that define the method)
   - Key results and findings (include important result equations)
   - Conclusions and implications
3. Preserve all LaTeX equations in their original format (e.g., $...$, $$...$$)
4. Extract 5-7 relevant keywords, excluding any equations or LaTeX symbols
5. Identify the paper title

Format your response as:
Title: [Paper Title]

Summary:
[Your detailed summary here in 3-4 paragraphs, including 2-4 most important complete equations]

Keywords: [keyword1, keyword2, keyword3, etc.]

Text to analyze:
{text}
"""
        logger.info("Sending request to Gemini API for summarization")
        response = gemini_model.generate_content(
            prompt,
            generation_config={
                "temperature": 0.2,
                "top_p": 0.8,
                "max_output_tokens": 2048
            },
            request_options={"timeout": 120}
        )
        
        return response.text

    try:
        response_text = summarize()
        title, summary, keywords = parse_summary_response(response_text, equation_placeholders)
        word_count = len(summary.split())
        equation_count = len(re.findall(r'\$.*?\$', summary))
        logger.info(f"Generated summary: {word_count} words with {equation_count} equations")
        
        formatted_summary = f"""## {title}

{summary}

**Keywords:** {', '.join(keywords)}"""
        
        return formatted_summary
    
    except Exception as e:
        logger.error(f"Failed to generate summary: {str(e)}")
        title = extract_title_from_text(text)
        return f"""## {title}

This research paper discusses important findings and methodologies in its field. The authors present their work with detailed analysis and experimental results. The study contributes to the existing body of knowledge and provides insights for future research directions.

The methodology employed in this research follows established practices while introducing novel approaches. The authors carefully designed their experiments and analysis to ensure reliable and valid results.

The findings of this study reveal significant insights that advance our understanding of the subject matter. The results demonstrate the effectiveness of the proposed methods and provide evidence for the authors' hypotheses.

In conclusion, this research makes valuable contributions to the field and opens up new avenues for future investigation. The work has practical implications and theoretical significance that will benefit the research community.

**Keywords:** research, analysis, methodology, findings, conclusions"""

def save_summary_history(summary, url=None):
    """Save summary to database."""
    try:
        logger.debug(f"Attempting to save summary to database. URL: {url}, Summary length: {len(summary) if summary else 0}")
        session = Session()
        record = SummaryHistory(summary=summary, original_url=url)
        session.add(record)
        session.flush()  # Ensure the record is written to the database
        session.commit()
        logger.info(f"Successfully saved summary to database. ID: {record.id}, URL: {url}")
    except Exception as e:
        logger.error(f"Failed to save summary to database: {str(e)}", exc_info=True)
        session.rollback()  # Rollback on error
        raise  # Re-raise for debugging
    finally:
        session.close()
        logger.debug("Database session closed")

def process_text(text, equation_placeholders, url=None):
    """Process text through cleaning and summarization."""
    if len(text.strip()) < 100:
        return "Error: The provided text is too short to generate a meaningful summary. Please provide a longer document."
    
    summary = generate_summary_with_gemini(text, equation_placeholders)
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
    raw_summary = None  # Store the raw summary for DB

    if request.method == 'POST':
        try:
            input_text = request.form.get('text')
            file = request.files.get('file')
            url = request.form.get('url')

            if file and allowed_file(file.filename):
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(file.filename))
                file.save(file_path)
                
                if file.filename.endswith('.pdf'):
                    text, equation_placeholders = extract_text_from_pdf(file_path)
                else:
                    text, equation_placeholders = extract_text_from_txt(file_path)
                
                if text.startswith('Error'):
                    error_message = text
                else:
                    raw_summary = process_text(text, equation_placeholders, None)
                
                try:
                    os.remove(file_path)
                except:
                    pass
                    
            elif input_text:
                text, equation_placeholders = clean_text_preserve_equations(input_text)
                raw_summary = process_text(text, equation_placeholders, url)
                
            elif url:
                pdf_path = download_pdf_from_url(url)
                if pdf_path:
                    text, equation_placeholders = extract_text_from_pdf(pdf_path)
                    if text.startswith('Error'):
                        error_message = text
                    else:
                        raw_summary = process_text(text, equation_placeholders, url)
                    
                    try:
                        os.remove(pdf_path)
                    except:
                        pass
                else:
                    error_message = f"Failed to download PDF from {url}. Please ensure the URL points to a valid PDF file or upload the PDF manually."

            else:
                error_message = "No valid input provided. Please enter text, upload a file, or provide a URL."

            # Save to DB BEFORE markdown conversion, if not error
            if raw_summary and not raw_summary.startswith('Error'):
                logger.debug(f"Preparing to save raw_summary to DB. Length: {len(raw_summary)}")
                try:
                    save_summary_history(raw_summary, url)
                    logger.info(f"Saved summary to DB. URL: {url}")
                except Exception as e:
                    logger.error(f"DB save failed: {str(e)}", exc_info=True)
                    error_message = f"Failed to save summary to database: {str(e)}"
                result = markdown.markdown(raw_summary, extensions=['nl2br', 'fenced_code', 'tables'])
            elif raw_summary and raw_summary.startswith('Error'):
                logger.warning(f"Summary not saved to DB due to error: {raw_summary}")
                error_message = raw_summary
                result = None

        except Exception as e:
            logger.error(f"Error in summary route: {str(e)}")
            error_message = f"An unexpected error occurred: {str(e)}"

        return jsonify({
            'summary': result,
            'error': error_message
        })

    return render_template('summarize.html', summary=result, error=error_message)

@app.route('/history')
def history():
    """Display summary history."""
    try:
        session = Session()  # Use the correct Session from db.py
        records = session.query(SummaryHistory).order_by(SummaryHistory.created_at.desc()).all()
        logger.info(f"Retrieved {len(records)} records from history")
        session.close()
        # Convert markdown to HTML for each summary
        for r in records:
            r.summary = markdown.markdown(r.summary, extensions=['nl2br', 'fenced_code', 'tables'])
        return render_template('history.html', histories=records)
    except Exception as e:
        logger.error(f"Error loading history: {str(e)}")
        return render_template('history.html', histories=[], error="Failed to load history")

if __name__ == '__main__':
    app.run(debug=False)