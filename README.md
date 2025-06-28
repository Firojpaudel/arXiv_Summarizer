# arXiv Summarizer: _Project Abstractify_<img src="static/img/large_icon.png" alt="Project Logo" width="95"/>

This is a Flask app that uses a fine-tuned BART model (trained on arXiv datasets) to summarize research papers. The goal was to create a simple, easy-to-use tool for researchers to get concise summaries of lengthy papers.

---

## Project Status  
The project is **completed**! Here's what it includes:  
1. A functional Flask app to upload research papers and generate summaries.  
2. A fallback mechanism that formats outputs via a T5 base model for improved readability.  

---

## 🛠️ Setup Instructions  

### Requirements  
- Python 3.8 or above.  
- Virtual environment tools like `conda` or `venv` are highly recommended.  

### Steps to Run the Project  
1. **Clone the repository:**
   ```bash
   git clone https://github.com/Firojpaudel/arXiv_Summarizer.git
   cd arXiv_Summarizer
   ```
2. **Set up a virtual environment** *(recommended)*:

    Using `conda`:
    ```bash
    conda create -n arxiv_summarizer python=3.10  
    conda activate arxiv_summarizer  
    ```
    Or using `venv`:
    ```bash
    python -m venv venv  
    source venv/bin/activate (Linux/Mac)  
    venv\Scripts\activate (Windows)
    ```
3. **Install dependencies:**

    ```bash
    pip install -r requirements.txt
    ```
4. **Download the fine_tuned_bart model:**

    The model is not included here due to its size. Please download it from the following link and place it inside the directory:

    [Download Model](https://drive.google.com/drive/u/2/folders/17bDdytEe0sLysZ-x2g0K4Rtyi1YhOw2p)
5. **Run the app:**

    ```bash
    python app.py
    ```
    The app will be hosted locally at `http://127.0.0.1:5000/`

---
## 🖼️ **How It Looks**

Here’s a quick preview of the app in action:

🏠 **Homepage:** 

<ul>
  This is where it all starts! Upload your research paper and get started.<br><br>
  <img src="./README_images/Homepage.png" alt="Homepage image" height="auto" width="100%">
</ul>

**📝 Summarization in Action:**

<ul>
  Once your paper is uploaded, the app gets to work, breaking down complex research into digestible summaries.<br><br>
  <img src="./README_images/Summarize.png" alt="Summarization in Action" height="auto" width="100%">
</ul>

**📄 Final Summary Output**

<ul>
  A clear, concise summary is generated for your research paper, formatted beautifully in markdown for readability.<br><br>
  <img src="./README_images/Summary_generated.png" alt="Generated Summary" height="auto" width="100%">
</ul>

---

## 🚀 What's New in This Version

- **Switched to Gemini 2.0 Flash:**  
  Thanks to generous token limits from Google, this version uses the Gemini 2.0 Flash model for summarization. This provides much faster and more consistent results compared to the previous BART-based approach.  
  > _BART was slow and inconsistent, even after fine-tuning. Gemini delivers better quality and speed for research paper summaries._

- **Summary History with Database:**  
  Every generated summary is now saved in a local SQLite database (`history.db`). You can view your entire summarization history from the web interface.  
  - See the new [`db.py`](db.py) file for the SQLAlchemy model and setup.
  - Summaries are stored with timestamps and (optionally) the original paper URL.

- **Proper LaTeX Equation Rendering:**  
  Summaries now preserve and render LaTeX equations beautifully, making mathematical content readable and clear.

- **Future Plans:**  
  - Experiment with fine-tuning larger models for local, faster, and more accurate summarization.
  - Explore GPU acceleration and more advanced model serving.

---

**🕑 Summary History:**

<ul>
  Every summary you generate is saved and can be revisited at any time!<br><br>
  <img src="./README_images/Summary_history.png" alt="Summary History Screenshot" height="auto" width="100%">
</ul>

---

## 📦 Database Model

See [`db.py`](db.py):

```python
class SummaryHistory(Base):
    __tablename__ = 'summary_history'
    id = Column(Integer, primary_key=True)
    summary = Column(Text, nullable=False)
    original_url = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
```

---
## 🧠 Learnings & Challenges
- **BART Limitations:** While BART worked for basic summarization, outputs were often inconsistent and slow, especially with diverse paper formats. Even after fine-tuning, it struggled with speed and quality.
- **Why Gemini 2.0 Flash:** Switched to Gemini 2.0 Flash for this version due to its speed, reliability, and generous token limits. It provides much better results for research paper summarization.
- **LaTeX Rendering:** Properly rendering LaTeX equations in summaries was a major challenge, but is now a highlight of this version.
- **Database Integration:** Added summary history with a persistent SQLite database, making it easy to revisit past summaries.
- **Future Directions:**
  - Plan to experiment with fine-tuning larger models and running local LLMs (e.g., using GRPO on larger parameter models) to improve reasoning and performance.
  - Explore local GPU acceleration and more advanced model serving for even faster and more accurate results.

---
## 📂 Repository Structure

```plaintext
arXiv_Summarizer/  
│  
├── app.py                   # Main Flask app (Gemini 2.0 Flash, summary logic, history)
├── db.py                    # SQLAlchemy models and database setup (summary history)
├── fine_tuned_bart/         # (Legacy) Directory for the fine-tuned BART model
├── t5-base/                 # (Legacy) Directory for T5 base model
├── templates/               # HTML templates (summarize.html, history.html, etc.)
├── static/                  # Static files (CSS, JS, images)
├── README_images/           # Images for README screenshots
├── requirements.txt         # Python dependencies
├── history.db               # SQLite database for summary history
└── README.md                # Project documentation (this file)    
```
---
## 🤝 Contributions & License

This project is licensed under the MIT License. Feel free to use, modify, and distribute it as per the license terms.

### How You Can Contribute

We welcome all contributors who want to add value to this project! Whether it's improving summarization quality, refining the interface, or optimizing performance, your contribution matters.

To contribute, follow these steps:

1. **Fork the repository.**

2. **Create your feature branch:**
   ```bash
   git checkout -b feature-name
   ```
3. **Commit your changes:**
    ```bash
    git commit -m "Added a cool new feature"
    ```
4. **Push to the branch:**
    ```bash
    git push origin feature-name
    ```
5. **Open a pull request.**

---
