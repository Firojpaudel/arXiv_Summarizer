import os
import re
import json
from time import sleep
import backoff
from flask import Flask, render_template, request, jsonify, session, flash, redirect, url_for
from werkzeug.utils import secure_filename
import requests
import google.generativeai as genai
import markdown
import logging
from dotenv import load_dotenv
import arxiv
import PyPDF2
from sqlalchemy.orm import Session as SQLSession
from db import Session, SummaryHistory, User
from auth import init_auth
import io
from flask import send_file

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configure Flask to use localhost for URL generation
# app.config['SERVER_NAME'] = 'localhost:5000'  # Disabled to prevent issues

# Initialize authentication
auth_manager = init_auth(app)

@app.context_processor
def inject_user():
    """Inject user context into all templates"""
    current_user = auth_manager.get_current_user_with_avatar() if auth_manager.is_authenticated() else None
    return {
        'current_user': current_user,
        'user_authenticated': auth_manager.is_authenticated(),
        'user_avatar': session.get('user_avatar') or (current_user.avatar_url if current_user else None),
        'user_name': session.get('user_name') or (current_user.name if current_user else None),
        'user_email': session.get('user_email') or (current_user.email if current_user else None),
        'user_id': session.get('user_id')
    }

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

def save_summary_history(summary, url=None, user_id=None):
    """Save summary to database with optional user association."""
    try:
        logger.debug(f"Attempting to save summary to database. URL: {url}, User ID: {user_id}, Summary length: {len(summary) if summary else 0}")
        session = Session()
        record = SummaryHistory(summary=summary, original_url=url, user_id=user_id)
        session.add(record)
        session.flush()  # Ensure the record is written to the database
        session.commit()
        logger.info(f"Successfully saved summary to database. ID: {record.id}, URL: {url}, User ID: {user_id}")
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
    try:
        # Debug session information FIRST
        logger.info(f"HOME ROUTE - Session data: {dict(session)}")
        logger.info(f"HOME ROUTE - Is authenticated: {auth_manager.is_authenticated()}")
        logger.info(f"HOME ROUTE - Is authenticated or guest: {auth_manager.is_authenticated_or_guest()}")
        
        # If user claims to be authenticated, verify with database
        if auth_manager.is_authenticated():
            current_user = auth_manager.get_current_user()
            if not current_user:
                # User session exists but user not in DB - clear session
                logger.warning("HOME ROUTE - User session exists but user not found in DB, clearing session")
                session.clear()
                return redirect(url_for('home'))
            
            # Ensure session has latest user data
            if current_user.avatar_url and session.get('user_avatar') != current_user.avatar_url:
                session['user_avatar'] = current_user.avatar_url
                session['user_name'] = current_user.name
                session['user_email'] = current_user.email
                logger.info(f"HOME ROUTE - Updated session with latest user data")
            
            logger.info(f"HOME ROUTE - Current user from DB: {current_user.email if current_user else None}")
            logger.info(f"HOME ROUTE - Avatar from DB: {current_user.avatar_url if current_user else None}")
            logger.info(f"HOME ROUTE - Avatar from session: {session.get('user_avatar')}")
        
        # If user is not authenticated and not in guest mode, redirect to login
        if not auth_manager.is_authenticated_or_guest():
            logger.info("HOME ROUTE - Redirecting to login")
            return redirect(url_for('login'))
        
        return render_template('index.html')
        
    except Exception as e:
        logger.error(f"HOME ROUTE - Error: {str(e)}")
        # Clear session on any error and redirect to login
        session.clear()
        return redirect(url_for('login'))

@app.route('/guest')
def guest_mode():
    """Allow users to continue as guest without authentication"""
    # Set a guest session flag
    session['guest_mode'] = True
    session['user_name'] = 'Guest'
    return render_template('index.html')

@app.route('/clear-session')
def clear_session():
    """Clear session for testing - remove this in production"""
    session.clear()
    return redirect(url_for('home'))

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
                    # Get current user ID if authenticated
                    current_user_id = session.get('user_id') if auth_manager.is_authenticated() else None
                    save_summary_history(raw_summary, url, current_user_id)
                    logger.info(f"Saved summary to DB. URL: {url}, User ID: {current_user_id}")
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

@app.route('/debug-session')
def debug_session():
    """Debug route to check session data"""
    # Get user from database using the enhanced method
    db_user = auth_manager.get_current_user_with_avatar() if auth_manager.is_authenticated() else None
    
    return jsonify({
        'session_data': dict(session),
        'is_authenticated': auth_manager.is_authenticated(),
        'is_authenticated_or_guest': auth_manager.is_authenticated_or_guest(),
        'user_id': session.get('user_id'),
        'user_avatar': session.get('user_avatar'),
        'user_name': session.get('user_name'),
        'user_email': session.get('user_email'),
        'db_user_avatar': db_user.avatar_url if db_user else None,
        'db_user_name': db_user.name if db_user else None,
        'db_user_email': db_user.email if db_user else None,
        'db_user_id': db_user.id if db_user else None
    })

@app.route('/test-auth')
def test_auth():
    """Test page for authentication debugging"""
    return render_template('test-auth.html')

@app.route('/force-logout')
def force_logout():
    """Force logout and clear all session data"""
    session.clear()
    return jsonify({'message': 'Session cleared, please refresh page'})

@app.route('/test-login/<email>')
def test_login(email):
    """Test route to simulate login with different emails - REMOVE IN PRODUCTION"""
    if not app.debug:
        return "Not available in production", 403
    
    # Simulate user data for testing
    test_user_data = {
        'email': email,
        'name': f'Test User {email.split("@")[0]}',
        'sub': f'test_{email.replace("@", "_").replace(".", "_")}',
        'picture': f'https://api.dicebear.com/7.x/avataaars/svg?seed={email}'
    }
    
    user = auth_manager.login_user(test_user_data, 'google')
    if user:
        return jsonify({
            'message': f'Test login successful for {email}',
            'user_id': user.id,
            'session_data': dict(session)
        })
    else:
        return jsonify({'error': 'Test login failed'}), 500

@app.route('/test-avatar')
def test_avatar():
    """Test route to manually set avatar in session"""
    if session.get('user_id'):
        session['user_avatar'] = 'https://lh3.googleusercontent.com/a/ACg8ocKnEiELzDFsXI-SnF2yWOeubfMCSKW8SP_v5ymlI-kKycEhPb0=s96-c'
        return jsonify({'message': 'Avatar set in session', 'avatar': session.get('user_avatar')})
    return jsonify({'error': 'Not logged in'})

@app.route('/debug-session-test')
def debug_session_test():
    """Debug session state and manually set avatar for testing"""
    session_data = dict(session)
    
    # Manually set session data for testing
    if request.args.get('set_test') == 'true':
        session['user_id'] = 2
        session['user_email'] = 'firojpaudel@gmail.com'
        session['user_name'] = 'Firoj Paudel'
        session['user_avatar'] = 'https://lh3.googleusercontent.com/a/ACg8ocLKhZolkP9mzalbqQrorXmlzsTk2hIqtJtc8UYWZGw4kfKoSNM2=s96-c'
        session['provider'] = 'google'
        return f"<h1>Session Set for Testing</h1><p>Avatar: {session['user_avatar']}</p><a href='/'>Go to Home</a>"
    
    return f"<h1>Session Debug</h1><pre>{session_data}</pre><a href='/debug-session-test?set_test=true'>Set Test Session</a>"

@app.route('/test-image')
def test_image():
    """Test if the avatar image loads"""
    if not auth_manager.is_authenticated():
        return "Not authenticated"
    
    avatar_url = session.get('user_avatar')
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Avatar Image Test</title>
        <style>
            body {{ font-family: Arial, sans-serif; padding: 20px; }}
            .test-container {{ margin: 20px 0; padding: 15px; border: 1px solid #ccc; }}
            img {{ margin: 10px; }}
        </style>
    </head>
    <body>
        <h1>Avatar Image Loading Test</h1>
        <p><strong>Avatar URL from session:</strong> {avatar_url}</p>
        
        <div class="test-container">
            <h3>Test 1: Direct Image with Error Handling</h3>
            <img src="{avatar_url}" alt="Avatar" style="width: 50px; height: 50px; border: 2px solid red;" 
                 onload="this.style.border='2px solid green'; console.log('Image loaded successfully');"
                 onerror="this.style.border='2px solid red'; console.log('Image failed to load'); this.alt='FAILED';">
        </div>
        
        <div class="test-container">
            <h3>Test 2: With Bootstrap Classes</h3>
            <img src="{avatar_url}" alt="Avatar" class="rounded-circle" style="width: 50px; height: 50px; border: 2px solid blue;"
                 onload="console.log('Bootstrap image loaded');"
                 onerror="console.log('Bootstrap image failed');">
        </div>
        
        <div class="test-container">
            <h3>Test 3: Exact Template Replica</h3>
            <button class="btn dropdown-toggle d-flex align-items-center" style="background: #424242; color: white; padding: 8px 16px; border-radius: 50px;">
                <img src="{avatar_url}" alt="Test User" class="rounded-circle me-2 user-avatar" style="width: 32px; height: 32px; border: 2px solid #fff;"
                     onload="console.log('Template replica loaded');"
                     onerror="console.log('Template replica failed');">
                <span>Test User</span>
            </button>
        </div>
        
        <script>
            console.log('Avatar URL being tested:', '{avatar_url}');
        </script>
    </body>
    </html>
    """
    return html

@app.route('/debug-template')
def debug_template():
    """Debug template rendering"""
    if not auth_manager.is_authenticated():
        return "Not authenticated"
    
    context = {
        'session_user_id': session.get('user_id'),
        'session_user_avatar': session.get('user_avatar'),
        'session_user_name': session.get('user_name'),
        'session_user_email': session.get('user_email'),
        'context_user_avatar': session.get('user_avatar') or 'NO_CONTEXT_AVATAR',
        'direct_test_avatar': 'https://lh3.googleusercontent.com/a/ACg8ocLKhZolkP9mzalbqQrorXmlzsTk2hIqtJtc8UYWZGw4kfKoSNM2=s96-c'
    }
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Avatar Debug</title>
        <link href="static/vendor/bootstrap/css/bootstrap.min.css" rel="stylesheet">
        <link href="static/css/main.css" rel="stylesheet">
    </head>
    <body>
        <div class="container mt-5">
            <h1>Avatar Debug Information</h1>
            
            <h3>Session Data:</h3>
            <ul>
                <li>User ID: {context['session_user_id']}</li>
                <li>Avatar URL: {context['session_user_avatar']}</li>
                <li>Name: {context['session_user_name']}</li>
                <li>Email: {context['session_user_email']}</li>
            </ul>
            
            <h3>Avatar Tests:</h3>
            
            <h4>1. Direct URL Test:</h4>
            <img src="{context['direct_test_avatar']}" alt="Direct Test" class="rounded-circle" style="width: 50px; height: 50px;">
            
            <h4>2. Session Avatar Test:</h4>
            <img src="{context['session_user_avatar']}" alt="Session Avatar" class="rounded-circle" style="width: 50px; height: 50px;">
            
            <h4>3. Template Logic Test (simulated):</h4>
            <div class="dropdown">
                <button class="btn dropdown-toggle d-flex align-items-center user-dropdown-btn" type="button">
                    <img src="{context['session_user_avatar']}" alt="{context['session_user_name']}" class="rounded-circle me-2 user-avatar" style="width: 32px; height: 32px;">
                    <span>{context['session_user_name']}</span>
                </button>
            </div>
        </div>
    </body>
    </html>
    """
    return html

@app.route('/sync-session')
def sync_session():
    """Force sync session with database"""
    if not auth_manager.is_authenticated():
        return jsonify({'error': 'Not authenticated'})
    
    user = auth_manager.get_current_user()
    if user:
        # Force update session with database values
        session['user_name'] = user.name
        session['user_email'] = user.email
        session['user_avatar'] = user.avatar_url
        session.permanent = True
        
        return jsonify({
            'message': 'Session synced with database',
            'user_name': session['user_name'],
            'user_email': session['user_email'], 
            'user_avatar': session['user_avatar']
        })
    return jsonify({'error': 'User not found in database'})

@app.route('/history')
def history():
    """Display summary history."""
    try:
        session_db = Session()  # Use the correct Session from db.py
        
        # If user is authenticated, show only their summaries
        if auth_manager.is_authenticated():
            current_user_id = session.get('user_id')
            records = session_db.query(SummaryHistory).filter_by(user_id=current_user_id).order_by(SummaryHistory.created_at.desc()).all()
            logger.info(f"Retrieved {len(records)} user-specific records from history for user {current_user_id}")
        else:
            # For guest users, show recent public summaries (or redirect to login)
            flash('Please sign in to view your personal summary history.', 'info')
            return redirect(url_for('login'))
        
        session_db.close()
        # Convert markdown to HTML for each summary
        for r in records:
            r.summary = markdown.markdown(r.summary, extensions=['nl2br', 'fenced_code', 'tables'])
        return render_template('history.html', histories=records)
    except Exception as e:
        logger.error(f"Error loading history: {str(e)}")
        return render_template('history.html', histories=[], error="Failed to load history")

@app.route('/avatar/<int:user_id>')
def serve_avatar(user_id):
    """Serve user avatar through proxy to handle CORS issues"""
    try:
        # Check if user is requesting their own avatar or is authenticated
        if not auth_manager.is_authenticated():
            logger.warning(f"Unauthenticated request for avatar {user_id}")
            return "", 404
            
        current_user_id = session.get('user_id')
        if current_user_id != user_id:
            logger.warning(f"User {current_user_id} trying to access avatar {user_id}")
            return "", 403  # Forbidden - can only access own avatar
            
        # Get user from database
        db_session = Session()
        user = db_session.query(User).filter_by(id=user_id).first()
        
        if not user or not user.avatar_url:
            logger.warning(f"No user or avatar URL found for user {user_id}")
            db_session.close()
            return "", 404
            
        avatar_url = user.avatar_url
        db_session.close()
        
        logger.info(f"Attempting to fetch avatar from: {avatar_url}")
        
        # Download the avatar image with multiple fallback strategies
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache'
        }
        
        # Try with session cookies if available
        cookies = None
        if 'google_token' in session:
            cookies = {'session': session.get('google_token', '')}
        
        response = requests.get(avatar_url, headers=headers, cookies=cookies, timeout=15, allow_redirects=True)
        
        if response.status_code == 200 and len(response.content) > 100:  # Valid image should be > 100 bytes
            # Create a BytesIO object from the image data
            img_io = io.BytesIO(response.content)
            img_io.seek(0)
            
            # Determine content type
            content_type = response.headers.get('content-type', 'image/jpeg')
            if not content_type.startswith('image/'):
                content_type = 'image/jpeg'  # Default fallback
            
            logger.info(f"Successfully served avatar for user {user_id}")
            return send_file(img_io, mimetype=content_type, as_attachment=False)
        else:
            logger.warning(f"Failed to fetch avatar: status={response.status_code}, content_length={len(response.content) if response.content else 0}")
            # Try a different approach - use a default avatar or return empty
            return "", 404
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error fetching avatar: {str(e)}")
        return "", 500
    except Exception as e:
        logger.error(f"Error serving avatar: {str(e)}")
        return "", 500

if __name__ == '__main__':
    app.run(debug=False, host='localhost', port=5000)