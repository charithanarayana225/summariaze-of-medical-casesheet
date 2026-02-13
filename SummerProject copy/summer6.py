import tkinter as tk
from tkinter import filedialog, messagebox
from textblob import TextBlob
import PyPDF2
import re
import os
import pytesseract
from PIL import Image
import shutil
import sys

tesseract_path = shutil.which("tesseract")

if tesseract_path:
    pytesseract.pytesseract.tesseract_cmd = tesseract_path
else:
    messagebox.showerror(
        "Tesseract OCR Not Found",
        "Tesseract-OCR is not installed or not in your PATH.\n\n"
        "👉 Install it with:\n   brew install tesseract\n\n"
        "Then restart the app."
    )
    sys.exit(1)
    
def extract_text_from_pdf(file_path):
    """
    Extracts text from a PDF file. Tries to extract selectable text first,
    then falls back to OCR for scanned PDFs.
    """
    text = ""
    try:
        with open(file_path, 'rb') as file:
            reader = PyPDF2.PdfReader(file)
            if any(page.extract_text() for page in reader.pages):
                for page in reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
                print("Text extracted successfully with PyPDF2.")
            else:
                print("No selectable text found. Attempting OCR.")
                
                for page_num in range(len(reader.pages)):
                    page = reader.pages[page_num]
                    writer = PyPDF2.PdfWriter()
                    writer.add_page(page)
                    
                    temp_pdf_path = "temp_page.pdf"
                    with open(temp_pdf_path, "wb") as temp_file:
                        writer.write(temp_file)
                    
                    try:
                        from pdf2image import convert_from_path
                        images = convert_from_path(temp_pdf_path)
                        for image in images:
                            text += pytesseract.image_to_string(image) + "\n"
                    except ImportError:
                        raise ImportError("`pdf2image` library is not installed. Please install it with `pip install pdf2image` and ensure `poppler` is on your system path for OCR to work.")
                    finally:
                        if os.path.exists(temp_pdf_path):
                            os.remove(temp_pdf_path)

    except FileNotFoundError:
        raise FileNotFoundError("The specified PDF file was not found.")
    except pytesseract.TesseractNotFoundError:
        raise RuntimeError("Tesseract-OCR is not installed or not in your system's PATH. Please install it to enable OCR for scanned PDFs.")
    except Exception as e:
        raise RuntimeError(f"An unexpected error occurred during PDF processing: {e}")
    
    if not text.strip():
        raise ValueError("Could not extract any text from the PDF, even with OCR. The file might be corrupted or in an unsupported format.")
    
    return text.strip()


def filter_relevant_text(text):
    """Filters out boilerplate and irrelevant information from the extracted text."""
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

def extract_sections(text):
    """Identifies and extracts key sections like 'Diagnosis' and 'Treatment Plan'."""
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

def summarize_text(text, sentence_count=5):
    """Summarizes text by taking the first few sentences."""
    blob = TextBlob(text)
    sentences = blob.sentences
    if not sentences:
        return text[:500] + ('...' if len(text) > 500 else '')
    return "\n".join(str(s) for s in sentences[:sentence_count])

def determine_patient_state(text):
    """Determines the patient's state based on keywords in the text."""
    text_lower = text.lower()

    normal_keywords = [
        "no complaints", "healthy", "routine checkup", "fit", "normal findings", "asymptomatic"
    ]
    taking_medicine_keywords = [
        "medication", "tablet", "capsule", "prescribed", "take medicine", "continue medicine",
        "on treatment", "course of antibiotics", "blood pressure control", "insulin", "dose"
    ]
    checkup_keywords = [
        "visit doctor", "consult", "appointment", "examination", "evaluation",
        "follow up", "symptoms", "fever", "pain", "nausea", "diagnosis pending"
    ]

    if any(k in text_lower for k in taking_medicine_keywords):
        return "💊 Taking Medicine: Patient is on a prescribed treatment plan and should continue medication as advised."
    elif any(k in text_lower for k in checkup_keywords):
        return "🩺 Checkup to a Doctor: Patient needs medical evaluation for symptoms or a routine examination."
    elif any(k in text_lower for k in normal_keywords):
        return "✅ Normal: Patient is generally healthy and requires no immediate medical attention."
    else:
        return "ℹ Unable to determine exact patient state from the given text."

def summarize_and_analyze(file_path):
    """Main function to process a PDF, extract text, generate a summary, and determine patient state."""
    text = extract_text_from_pdf(file_path)
    text = filter_relevant_text(text)
    sections = extract_sections(text)

    summary_parts = []
    for section_name in [
        'history', 'chief complaint', 'presenting complaint', 'problem summary',
        'diagnosis', 'assessment', 'treatment plan', 'plan', 'suggestion', 'advice'
    ]:
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
            suggestion = "⚠ Patient may need urgent attention. Refer immediately."
        else:
            suggestion = "🔍 Monitor progress and revisit if symptoms persist."
        summary_parts.append(f"💡 Suggestion:\n{suggestion}")

    # Add patient state
    patient_state = determine_patient_state(text)
    summary_parts.append(f"\n📌 Patient State:\n{patient_state}")

    full_summary = "\n".join(summary_parts)

    save_path = os.path.splitext(file_path)[0] + "_summary.txt"
    with open(save_path, 'w', encoding='utf-8') as f:
        f.write(full_summary)

    return full_summary

def upload_file():
    """Handles file upload and calls the summarization process."""
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