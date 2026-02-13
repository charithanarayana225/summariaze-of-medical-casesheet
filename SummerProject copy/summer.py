import tkinter as tk
from tkinter import filedialog, messagebox
from textblob import TextBlob
import PyPDF2
import pytesseract
from PIL import Image, ImageEnhance
import fitz  # PyMuPDF
import io
import re
import os


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

            # Preprocess image for OCR
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
        # Filter lines with too many digits (IDs, phone numbers)
        if len(re.findall(r'\d', line)) > len(line) / 3:
            continue
        # Filter boilerplate/hospital phrases
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

def extract_sections(text):
    sections = {}
    headings = [
        'History', 'Chief Complaint', 'Presenting Complaint',
        'Diagnosis', 'Assessment', 'Problem Summary',
        'Treatment Plan', 'Plan', 'Suggestion', 'Advice'
    ]

    # Use case-insensitive multiline regex to find headings
    pattern = rf'(?im)^({"|".join([re.escape(h) for h in headings])})[:\-]?'
    splits = re.split(pattern, text)
    found_headings = re.findall(pattern, text)

    if found_headings:
        # splits list format: [text_before_first_heading, heading1, content1, heading2, content2, ...]
        for i, heading in enumerate(found_headings):
            content_index = 2*i + 2
            content = splits[content_index].strip() if content_index < len(splits) else ''
            sections[heading.lower()] = content
    else:
        sections['full_text'] = text

    return sections

def summarize_text(text, sentence_count=5):
    blob = TextBlob(text)
    sentences = blob.sentences
    if not sentences:
        return text[:500] + ('...' if len(text) > 500 else '')
    return "\n".join(str(s) for s in sentences[:sentence_count])

def summarize_and_analyze(file_path):
    text = extract_text_from_pdf(file_path)
    if not text:
        text = extract_text_with_ocr(file_path)
    if not text.strip():
        raise ValueError("No readable text found in the case sheet.")

    text = filter_relevant_text(text)

    sections = extract_sections(text)

    summary_parts = []
    for section_name in ['history', 'chief complaint', 'presenting complaint', 'problem summary', 'diagnosis', 'assessment', 'treatment plan', 'plan', 'suggestion', 'advice']:
        content = sections.get(section_name)
        if content:
            content = filter_relevant_text(content)
            summary = summarize_text(content)
            summary_parts.append(f"🩺 {section_name.title()}:\n{summary}\n")

    if not summary_parts:
        summary_parts.append("🩺 Summary:\n" + summarize_text(text))

    if not any(k in sections for k in ['suggestion', 'advice', 'plan', 'treatment plan']):
        polarity = TextBlob(text).sentiment.polarity
        if polarity > 0.2:
            suggestion = "✅ Patient condition is stable. Continue treatment and review later."
        elif polarity < -0.2:
            suggestion = "⚠️ Patient may need urgent attention. Refer immediately."
        else:
            suggestion = "🔍 Monitor progress and revisit if symptoms persist."
        summary_parts.append(f"💡 Suggestion:\n{suggestion}")

    full_summary = "\n".join(summary_parts)

    save_path = os.path.splitext(file_path)[0] + "_summary.txt"
    with open(save_path, 'w', encoding='utf-8') as f:
        f.write(full_summary)

    return full_summary

def upload_file():
    file_path = filedialog.askopenfilename(filetypes=[("PDF files", "*.pdf")])
    if file_path:
        try:
            summary = summarize_and_analyze(file_path)
            messagebox.showinfo("Patient Summary", summary)
        except Exception as e:
            messagebox.showerror("Error", str(e))

# GUI Setup
window = tk.Tk()
window.title("🩺 Medical Case Sheet Summarizer")

label = tk.Label(window, text="📄 Upload a Medical Case Sheet PDF", font=("Arial", 12))
label.pack(pady=10)

upload_button = tk.Button(window, text="Upload Case Sheet", command=upload_file, font=("Arial", 10))
upload_button.pack(pady=5)

window.geometry("500x200")
window.mainloop()