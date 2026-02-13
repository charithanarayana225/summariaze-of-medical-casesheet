from flask import Flask, request, render_template, jsonify, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import PyPDF2
import pytesseract
from PIL import Image, ImageEnhance
import fitz  # PyMuPDF
import io
import re
from textblob import TextBlob
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.decomposition import TruncatedSVD
import numpy as np
import sqlite3
import os
from datetime import datetime
from transformers import pipeline
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import nltk
nltk.download('punkt')

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'  # Replace with a secure key
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Database setup
def init_db():
    with sqlite3.connect('summaries.db') as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users 
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                      username TEXT UNIQUE NOT NULL, 
                      password TEXT NOT NULL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS summaries 
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                      user_id INTEGER, 
                      filename TEXT, 
                      summary TEXT, 
                      created_at TIMESTAMP, 
                      FOREIGN KEY (user_id) REFERENCES users (id))''')
        conn.commit()

init_db()

# User model for Flask-Login
class User(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

@login_manager.user_loader
def load_user(user_id):
    with sqlite3.connect('summaries.db') as conn:
        c = conn.cursor()
        c.execute("SELECT id, username FROM users WHERE id = ?", (user_id,))
        user_data = c.fetchone()
        if user_data:
            return User(user_data[0], user_data[1])
        return None

def extract_text_from_pdf(file_path):
    text = ""
    try:
        with open(file_path, 'rb') as file:
            reader = PyPDF2.PdfReader(file)
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
    except Exception as e:
        raise RuntimeError(f"Error reading PDF: {str(e)}")
    return text.strip()

def extract_text_with_ocr(pdf_path):
    try:
        doc = fitz.open(pdf_path)
        text = ""
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            pix = page.get_pixmap(dpi=300)
            img_data = pix.tobytes("png")
            image = Image.open(io.BytesIO(img_data))
            image = image.convert('L')
            image = image.point(lambda x: 0 if x < 140 else 255)
            image = ImageEnhance.Contrast(image).enhance(2.5)
            image = ImageEnhance.Sharpness(image).enhance(2.0)
            ocr_result = pytesseract.image_to_string(image, lang='eng', config='--oem 3 --psm 4')
            text += ocr_result + "\n"
        return text.strip()
    except Exception as e:
        raise RuntimeError(f"OCR failed: {str(e)}")

def filter_relevant_text(text):
    lines = text.split('\n')
    filtered_lines = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if len(re.findall(r'\d', line)) > len(line) / 3:
            continue
        boilerplate_phrases = [
            'hospital', 'patient card', 'registration', 'general hospital',
            'medical records', 'department', 'address', 'phone', 'fax', 'email',
            'date of surgery', 'date:', 'time:', 'patient id', 'record no',
            'summary sheet department', 'emergency', 'insurance'
        ]
        if any(phrase in line.lower() for phrase in boilerplate_phrases):
            continue
        filtered_lines.append(line)
    return "\n".join(filtered_lines)

def extract_disease_lsa(text, n_components=2):
    sentences = text.split('\n')
    if not sentences:
        return "No disease identified", []

    vectorizer = TfidfVectorizer(stop_words='english')
    try:
        X = vectorizer.fit_transform(sentences)
    except ValueError:
        return "No disease identified", []

    svd = TruncatedSVD(n_components=n_components)
    lsa_matrix = svd.fit_transform(X)
    terms = vectorizer.get_feature_names_out()
    components = svd.components_

    disease_keywords = []
    for component in components:
        top_term_indices = component.argsort()[-5:][::-1]
        disease_keywords.extend([terms[i] for i in top_term_indices])

    relevant_sentences = [s for s in sentences if any(kw in s.lower() for kw in disease_keywords)]
    disease_summary = " ".join(disease_keywords[:3]) if disease_keywords else "No disease identified"
    return disease_summary, relevant_sentences

def bert_summarize(text, max_sentences=3):
    summarizer = pipeline("summarization", model="facebook/bart-large-cnn")
    max_input_length = 512  # BART's max input length
    text = text[:max_input_length]
    summary = summarizer(text, max_length=100, min_length=30, do_sample=False)
    sentences = nltk.sent_tokenize(summary[0]['summary_text'])
    return "\n".join(sentences[:max_sentences])

def analyze_patient_status(text):
    blob = TextBlob(text)
    polarity = blob.sentiment.polarity
    if polarity > 0.2:
        return "Stable: Patient condition appears positive."
    elif polarity < -0.2:
        return "Critical: Patient may require urgent attention."
    return "Monitor: Patient condition needs regular observation."

def extract_sections(text):
    sections = {}
    headings = [
        'History', 'Chief Complaint', 'Presenting Complaint',
        'Diagnosis', 'Assessment', 'Problem Summary',
        'Treatment Plan', 'Plan', 'Suggestion', 'Advice'
    ]
    pattern = rf'(?im)^({"|".join([re.escape(h) for h in headings])})[:\-]?'
    splits = re.split(pattern, text)
    found_headings = re.findall(pattern, text)

    if found_headings:
        for i, heading in enumerate(found_headings):
            content_index = 2*i + 2
            content = splits[content_index].strip() if content_index < len(splits) else ''
            sections[heading.lower()] = content
    else:
        sections['full_text'] = text
    return sections

@app.route('/')
@login_required
def index():
    return render_template('index.html', username=current_user.username)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        try:
            with sqlite3.connect('summaries.db') as conn:
                c = conn.cursor()
                c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, hashed_password))
                conn.commit()
            flash('Registration successful! Please log in.', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Username already exists.', 'error')
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        with sqlite3.connect('summaries.db') as conn:
            c = conn.cursor()
            c.execute("SELECT id, username, password FROM users WHERE username = ?", (username,))
            user_data = c.fetchone()
            if user_data and check_password_hash(user_data[2], password):
                user = User(user_data[0], user_data[1])
                login_user(user)
                return redirect(url_for('index'))
            flash('Invalid username or password.', 'error')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out successfully.', 'success')
    return redirect(url_for('login'))

@app.route('/upload', methods=['POST'])
@login_required
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'})
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'})
    
    if file and file.filename.endswith('.pdf'):
        try:
            file_path = os.path.join('uploads', file.filename)
            os.makedirs('uploads', exist_ok=True)
            file.save(file_path)

            text = extract_text_from_pdf(file_path)
            if not text:
                text = extract_text_with_ocr(file_path)
            if not text.strip():
                raise ValueError("No readable text found in the case sheet.")

            text = filter_relevant_text(text)
            sections = extract_sections(text)

            disease, relevant_sentences = extract_disease_lsa(text)
            disease_summary = f"🩺 Identified Disease: {disease}\n" + "\n".join(relevant_sentences[:3])

            summary_parts = []
            for section_name in ['history', 'chief complaint', 'presenting complaint', 'problem summary', 'diagnosis', 'assessment', 'treatment plan', 'plan', 'suggestion', 'advice']:
                content = sections.get(section_name)
                if content:
                    content = filter_relevant_text(content)
                    summary = bert_summarize(content)
                    summary_parts.append(f"📝 {section_name.title()}:\n{summary}\n")

            if not summary_parts:
                summary_parts.append("📝 Summary:\n" + bert_summarize(text))

            status = analyze_patient_status(text)
            summary_parts.append(f"💡 Patient Status:\n{status}")

            full_summary = "\n".join([disease_summary] + summary_parts)

            with sqlite3.connect('summaries.db') as conn:
                c = conn.cursor()
                c.execute("INSERT INTO summaries (user_id, filename, summary, created_at) VALUES (?, ?, ?, ?)",
                          (current_user.id, file.filename, full_summary, datetime.utcnow()))
                conn.commit()

            os.remove(file_path)

            return jsonify({'summary': full_summary})
        except Exception as e:
            return jsonify({'error': str(e)})
    return jsonify({'error': 'Invalid file format'})

@app.route('/history')
@login_required
def history():
    with sqlite3.connect('summaries.db') as conn:
        c = conn.cursor()
        c.execute("SELECT filename, summary, created_at FROM summaries WHERE user_id = ? ORDER BY created_at DESC",
                  (current_user.id,))
        summaries = c.fetchall()
    return render_template('history.html', summaries=summaries)

if __name__ == '__main__':
    app.run(debug=True)