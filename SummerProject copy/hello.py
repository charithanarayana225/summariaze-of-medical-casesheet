import tkinter as tk
from tkinter import filedialog, messagebox
from pdf2image import convert_from_path
import pytesseract
from gensim.summarization import summarize
import os

# If Tesseract is not in PATH, set it manually here (use your actual installed path)
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# Text extraction using OCR from image-based PDF
def extract_text_from_pdf(file_path):
    try:
        images = convert_from_path(file_path)
        full_text = ""
        for img in images:
            text = pytesseract.image_to_string(img)
            full_text += text + "\n"
        return full_text
    except Exception as e:
        messagebox.showerror("Error", f"Failed to extract text: {e}")
        return ""

# Summarize text using Gensim's TextRank
def summarize_text(text):
    try:
        if len(text.split('.')) < 3:
            return "Text too short to summarize."
        summary = summarize(text, ratio=0.3)  # 30% of original
        return summary if summary else "Could not generate summary."
    except Exception as e:
        return f"Summarization error: {str(e)}"

# Main summarization function
def summarize_and_analyze(file_path):
    text = extract_text_from_pdf(file_path)
    summary = summarize_text(text)
    output_text.delete(1.0, tk.END)
    output_text.insert(tk.END, "------ Extracted Text ------\n")
    output_text.insert(tk.END, text)
    output_text.insert(tk.END, "\n\n------ Summary ------\n")
    output_text.insert(tk.END, summary)

# File selection via GUI
def browse_file():
    file_path = filedialog.askopenfilename(filetypes=[("PDF Files", "*.pdf")])
    if file_path:
        summarize_and_analyze(file_path)

# GUI Setup
root = tk.Tk()
root.title("Medical Case Sheet Analyzer")
root.geometry("900x700")

browse_btn = tk.Button(root, text="Select Medical PDF", command=browse_file)
browse_btn.pack(pady=10)

output_text = tk.Text(root, wrap=tk.WORD)
output_text.pack(expand=True, fill=tk.BOTH, padx=10, pady=10)

root.mainloop()