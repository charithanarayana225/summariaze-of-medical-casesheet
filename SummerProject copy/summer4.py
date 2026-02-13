import tkinter as tk
from tkinter import filedialog, messagebox
from textblob import TextBlob
import PyPDF2
import re
import os

def extract_text_from_pdf(file_path):
    """
    Extracts text from a PDF file using PyPDF2.
    This method only works for PDFs with selectable text, not scanned images.
    """
    text = ""
    try:
        with open(file_path, 'rb') as file:
            reader = PyPDF2.PdfReader(file)
            if len(reader.pages) == 0:
                raise ValueError("The PDF appears to be empty or an image-based file without selectable text.")

            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
    except Exception as e:
        raise RuntimeError(f"Error reading PDF: {str(e)}")
    
    if not text.strip():
        raise ValueError("No selectable text found in the PDF. This file may be a scan.")
    
    return text.strip()

def filter_relevant_text(text):
    """
    Filters out boilerplate and irrelevant information from the extracted text.
    """
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
    """
    Identifies and extracts key sections like 'Diagnosis' and 'Treatment Plan'.
    """
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
        for i, heading in enumerate(found_headings):
            content_index = 2*i + 2
            content = splits[content_index].strip() if content_index < len(splits) else ''
            sections[heading.lower()] = content
    else:
        sections['full_text'] = text

    return sections

def summarize_text(text, sentence_count=5):
    """
    Summarizes text by taking the first few sentences.
    """
    blob = TextBlob(text)
    sentences = blob.sentences
    if not sentences:
        return text[:500] + ('...' if len(text) > 500 else '')
    return "\n".join(str(s) for s in sentences[:sentence_count])

def summarize_and_analyze(file_path):
    """
    Main function to process a PDF, extract text, and generate a summary.
    """
    # Only rely on PyPDF2 for text extraction
    text = extract_text_from_pdf(file_path)

    text = filter_relevant_text(text)
    sections = extract_sections(text)

    summary_parts = []
    # Order of sections to display in the summary
    for section_name in ['history', 'chief complaint', 'presenting complaint', 'problem summary', 'diagnosis', 'assessment', 'treatment plan', 'plan', 'suggestion', 'advice']:
        content = sections.get(section_name)
        if content:
            content = filter_relevant_text(content)
            summary = summarize_text(content)
            summary_parts.append(f"🩺 {section_name.title()}:\n{summary}\n")

    if not summary_parts:
        # Fallback to a general summary if no specific sections were found
        summary_parts.append("🩺 Summary:\n" + summarize_text(text))

    if not any(k in sections for k in ['suggestion', 'advice', 'plan', 'treatment plan']):
        # Sentiment analysis as a fallback for suggestions
        polarity = TextBlob(text).sentiment.polarity
        if polarity > 0.2:
            suggestion = "✅ Patient condition is stable. Continue treatment and review later."
        elif polarity < -0.2:
            suggestion = "⚠ Patient may need urgent attention. Refer immediately."
        else:
            suggestion = "🔍 Monitor progress and revisit if symptoms persist."
        summary_parts.append(f"💡 Suggestion:\n{suggestion}")

    full_summary = "\n".join(summary_parts)

    save_path = os.path.splitext(file_path)[0] + "_summary.txt"
    with open(save_path, 'w', encoding='utf-8') as f:
        f.write(full_summary)

    return full_summary

def upload_file():
    """
    Handles the file upload and calls the summarization process.
    """
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