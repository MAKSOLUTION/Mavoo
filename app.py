import fitz
import re
import os
import logging
import zipfile
from flask import Flask, request, jsonify, send_file, render_template
from werkzeug.utils import secure_filename

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev_key")

UPLOAD_FOLDER = "uploads"
OUTPUT_FOLDER = "split_invoices"
STATIC_FOLDER = "static"
IMAGES_FOLDER = os.path.join(STATIC_FOLDER, "images")
ALLOWED_EXTENSIONS = {'pdf', 'zip'}

# Create necessary directories
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)
os.makedirs(IMAGES_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route("/")
def home():
    return render_template('index.html')

@app.route("/upload", methods=["POST"])
def upload_pdf():
    try:
        if "file" not in request.files:
            return jsonify({"error": "No file part"}), 400

        file = request.files["file"]
        gstin_filter = request.form.get("gstin", "").strip()

        if file.filename == "":
            return jsonify({"error": "No selected file"}), 400

        if not allowed_file(file.filename):
            return jsonify({"error": "Invalid file type. Only PDF and ZIP files are allowed."}), 400

        filename = secure_filename(file.filename)
        file_path = os.path.join(UPLOAD_FOLDER, filename)
        file.save(file_path)
        logger.debug(f"File saved to {file_path}")

        split_files = []

        if filename.lower().endswith('.zip'):
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                # Extract only PDF files
                pdf_files = [f for f in zip_ref.namelist() if f.lower().endswith('.pdf')]
                for pdf_file in pdf_files:
                    extracted_path = os.path.join(UPLOAD_FOLDER, secure_filename(pdf_file))
                    with zip_ref.open(pdf_file) as source, open(extracted_path, 'wb') as target:
                        target.write(source.read())
                    split_files.extend(split_invoices(extracted_path, gstin_filter))
                    os.remove(extracted_path)  # Clean up extracted PDF
        else:
            split_files = split_invoices(file_path, gstin_filter)

        logger.debug(f"Split into {len(split_files)} files")

        return jsonify({
            "message": "Files processed successfully!",
            "files": split_files
        })
    except Exception as e:
        logger.error(f"Error processing file: {str(e)}")
        return jsonify({"error": "An error occurred while processing the file"}), 500

def split_invoices(input_pdf, gstin_filter=None):
    doc = fitz.open(input_pdf)
    split_files = []

    doc_pattern = re.compile(r"Document No. : (\S+)")
    gst_pattern = re.compile(r"Recipient\s+:\s+GSTIN\s+:\s+(\S+)")

    invoice_pages = []
    invoice_data = []

    try:
        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text("text")
            logger.debug(f"Processing page {page_num + 1}")

            doc_match = doc_pattern.search(text)
            gst_match = gst_pattern.search(text)

            if doc_match and gst_match:
                if invoice_pages:
                    # Save previous invoice if it matches the GSTIN filter
                    current_gstin = invoice_data[1]
                    if not gstin_filter or gstin_filter.upper() == current_gstin.upper():
                        filename = secure_filename(f"{invoice_data[0]}_{invoice_data[1]}.pdf")
                        output_path = os.path.join(OUTPUT_FOLDER, filename)

                        new_pdf = fitz.open()
                        for p in invoice_pages:
                            new_pdf.insert_pdf(doc, from_page=p, to_page=p)
                        new_pdf.save(output_path)
                        new_pdf.close()
                        split_files.append(filename)
                        logger.debug(f"Saved split PDF: {filename}")

                invoice_pages = [page_num]
                invoice_data = [doc_match.group(1), gst_match.group(1)]
            else:
                if invoice_pages:  # Only append if we've already started an invoice
                    invoice_pages.append(page_num)

        # Process the last invoice
        if invoice_pages:
            current_gstin = invoice_data[1]
            if not gstin_filter or gstin_filter.upper() == current_gstin.upper():
                filename = secure_filename(f"{invoice_data[0]}_{invoice_data[1]}.pdf")
                output_path = os.path.join(OUTPUT_FOLDER, filename)

                new_pdf = fitz.open()
                for p in invoice_pages:
                    new_pdf.insert_pdf(doc, from_page=p, to_page=p)
                new_pdf.save(output_path)
                new_pdf.close()
                split_files.append(filename)
                logger.debug(f"Saved final split PDF: {filename}")

    except Exception as e:
        logger.error(f"Error in split_invoices: {str(e)}")
        raise
    finally:
        doc.close()

    return split_files

@app.route("/download/<filename>")
def download_file(filename):
    try:
        return send_file(
            os.path.join(OUTPUT_FOLDER, filename),
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        logger.error(f"Error downloading file: {str(e)}")
        return jsonify({"error": "File not found"}), 404

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)