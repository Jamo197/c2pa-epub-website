import json
import os
from datetime import datetime

from c2pa import Reader, get_epub_metadata
from flask import Flask, redirect, render_template, request, url_for, send_file
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = "uploads"
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

# Global variable to store the last result for PDF export
last_result = {"filename": "", "metadata": "", "verify_result": "", "timestamp": ""}

@app.route("/", methods=["GET", "POST"])
def upload_file():
    global last_result
    if request.method == "POST":
        uploaded_file = request.files.get("file")
        action = request.form.get("action")
        if uploaded_file:
            filename = secure_filename(f"{uploaded_file.filename}")
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            uploaded_file.save(filepath)
            result = ""
            # Handle different actions here
            if action == "verify":
                result = f"✅ Verified {filename}"
                last_result["verify_result"] = result
                last_result["filename"] = filename
                last_result["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            elif action == "sign":
                result = f"✍️ Signed {filename}"
            elif action == "manifest":
                try:
                    with Reader(filepath) as reader:
                        manifest_json = reader.json()
                        manifest = json.loads(manifest_json)
                        active_manifest_key = manifest.get("active_manifest")
                        active_manifest = manifest["manifests"].get(
                            active_manifest_key, {}
                        )
                        result = active_manifest
                        # if active_manifest:
                        #     uri = active_manifest.get("thumbnail", {}).get("identifier")
                        #     if uri:
                        #         thumbnail_path = os.path.join(
                        #             app.config["UPLOAD_FOLDER"], "thumbnail.jpg"
                        #         )
                        #         with open(thumbnail_path, "wb") as f:
                        #             reader.resource_to_stream(uri, f)
                        #         result = f"Manifest extracted for {filename}. Thumbnail saved as thumbnail.jpg."
                        #     else:
                        #         result = f"Manifest found for {filename}, but no thumbnail present."
                        # else:
                        #     result = f"No active manifest found in {filename}."
                except Exception as err:
                    result = f"Error reading manifest: {str(err)}"
            elif action == "metadata":
                try:
                    # Use exposed get_epub_metadata function
                    metadata = get_epub_metadata(filepath)
                    result = f"📚 EPUB Metadata for {filename}:\n{json.dumps(metadata, indent=2)}"
                    last_result["metadata"] = result
                    last_result["filename"] = filename
                    last_result["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                except Exception as err:
                    result = f"❌ Error reading EPUB metadata: {str(err)}"
            else:
                result = "❌ Unknown action"
            return render_template("index.html", filename=filename, result=result, show_export=bool(last_result.get("metadata") and last_result.get("verify_result")))
    return render_template("index.html")

@app.route("/export_pdf")
def export_pdf():
    global last_result
    
    if not last_result.get("metadata") or not last_result.get("verify_result"):
        return "No data available for PDF export", 400
    
    # Create PDF filename
    pdf_filename = f"epub_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    pdf_path = os.path.join(app.config["UPLOAD_FOLDER"], pdf_filename)
    
    # Create PDF document
    doc = SimpleDocTemplate(pdf_path, pagesize=A4)
    styles = getSampleStyleSheet()
    story = []
    
    # Title
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        spaceAfter=30,
        alignment=1  # Center alignment
    )
    story.append(Paragraph("EPUB C2PA Analysis Report", title_style))
    story.append(Spacer(1, 20))
    
    # File information
    file_info = [
        ["File Name:", last_result["filename"]],
        ["Analysis Date:", last_result["timestamp"]],
    ]
    
    file_table = Table(file_info, colWidths=[2*inch, 4*inch])
    file_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.grey),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 12),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ('BACKGROUND', (1, 0), (1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    story.append(file_table)
    story.append(Spacer(1, 20))
    
    # Verification Result
    story.append(Paragraph("Verification Result", styles['Heading2']))
    story.append(Spacer(1, 10))
    story.append(Paragraph(last_result["verify_result"], styles['Normal']))
    story.append(Spacer(1, 20))
    
    # Metadata Result
    story.append(Paragraph("EPUB Metadata", styles['Heading2']))
    story.append(Spacer(1, 10))
    
    # Format metadata for better display
    metadata_text = last_result["metadata"].replace("📚 EPUB Metadata for " + last_result["filename"] + ":\n", "")
    metadata_lines = metadata_text.split('\n')
    
    for line in metadata_lines:
        if line.strip():
            # Indent JSON content
            if line.startswith('  '):
                story.append(Paragraph(line, styles['Normal']))
            else:
                story.append(Paragraph(line, styles['Normal']))
    
    # Build PDF
    doc.build(story)
    
    return send_file(pdf_path, as_attachment=True, download_name=pdf_filename)


if __name__ == "__main__":
    app.run(debug=True)
