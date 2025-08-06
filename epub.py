import base64
import hashlib
import json
import mimetypes
import os
import shutil
import zipfile
from datetime import datetime

from c2pa import Builder, C2paSignerInfo, Reader, Signer, get_epub_metadata
from flask import Flask, render_template, request, send_file
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = "uploads"
app.config["OUTPUT_FOLDER"] = "outputs"
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
os.makedirs(app.config["OUTPUT_FOLDER"], exist_ok=True)

CERT_PATH = os.path.join("cert", "ps256.pub")
PRIVATE_KEY_PATH = os.path.join("cert", "ps256.pem")


def add_file_assertion_to_manifest(filepath):
    with zipfile.ZipFile(filepath, "r") as zf:
        uris = []
        for info in zf.infolist():
            if info.is_dir():
                continue
            with zf.open(info.filename) as file:
                file_data = file.read()
                file_hash = hashlib.sha256(file_data).digest()
                hash_b64 = base64.b64encode(file_hash).decode("utf-8")
                mime_type, _ = mimetypes.guess_type(info.filename)
                uris.append(
                    {
                        "uri": info.filename,
                        "hash": hash_b64,
                        "dc:format": mime_type or "application/octet-stream",
                        "size": info.file_size,
                    }
                )
    return {"alg": "sha256", "uris": uris}


def add_zip_assertion(filepath):
    with open(filepath, "rb") as f:
        file_data = f.read()
    file_hash = hashlib.sha256(file_data).digest()
    hash_b64 = base64.b64encode(file_hash).decode("utf-8")
    return {
        "alg": "sha256",
        "pad": "0000",
        "hash": hash_b64,
    }


def build_manifest_json(filepath):
    file_assertions = add_file_assertion_to_manifest(filepath)
    manifest = {
        "claim_generator": "python_test/0.1",
        "assertions": [
            {
                "label": "c2pa.hash.collection.data",
                "data": file_assertions,
            },
            {
                "label": "c2pa.hash.data",
                "data": add_zip_assertion(filepath),
            },
        ],
    }
    return json.dumps(manifest)


def sign_epub(filepath, filename):
    output_path = os.path.join(app.config["OUTPUT_FOLDER"], f"output_{filename}")

    shutil.copy(filepath, output_path)

    with open(CERT_PATH, "rb") as cert_file, open(PRIVATE_KEY_PATH, "rb") as key_file:
        cert_data = cert_file.read()
        key_data = key_file.read()

        signer_info = C2paSignerInfo(
            alg=b"ps256",
            sign_cert=cert_data,
            private_key=key_data,
            ta_url=b"http://timestamp.digicert.com",
        )
        signer = Signer.from_info(signer_info)

        manifest_json = build_manifest_json(filepath)

        builder = Builder(manifest_json)

        with open(filepath, "rb") as ingredient_file:
            builder.add_ingredient(
                ingredient_json=json.dumps(
                    {
                        "title": f"File name: {filename}",
                        "format": "application/epub+zip",
                    }
                ),
                format="application/epub+zip",
                source=ingredient_file,
            )

        # Open both source and destination files
        with open(filepath, "rb") as source_file, open(output_path, "r+b") as dest_file:
            manifest_bytes = builder.sign(
                signer, "application/epub+zip", source_file, dest_file
            )

        with open(output_path, "rb") as stream:
            # Create a Reader to read data
            with Reader("application/epub+zip", stream) as reader:
                manifest_store = json.loads(reader.json())
                active_manifest = manifest_store["manifests"][
                    manifest_store["active_manifest"]
                ]
                return "Signed manifest:", active_manifest


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
            json_result = ""
            if action == "verify":
                result = f"Verified {filename}"
                try:
                    with open(filepath, "rb") as stream:
                        with Reader(
                            format_or_path="application/epub+zip", stream=stream
                        ) as reader:
                            result = ""
                            manifest_json = reader.json()
                            manifest = json.loads(manifest_json)
                            validation_results = manifest["validation_results"][
                                "activeManifest"
                            ]
                            for status in ["success", "informational", "failure"]:
                                if status == "success":
                                    result += f"<h3>✅ Status {status}:</h3>"
                                elif status == "informational":
                                    result += f"<h3>ℹ️ Status {status}:</h3>"
                                elif status == "failure":
                                    result += f"<h3>❌ Status {status}:</h3>"
                                for i, validation in enumerate(
                                    validation_results[status]
                                ):
                                    if not validation:
                                        continue
                                    result += f"{i + 1}. <b>{validation['code']}</b>: {validation['explanation']}<br>"
                except Exception as err:
                    result = f"Error reading manifest: {str(err)}"
            elif action == "sign":
                try:
                    json_result = sign_epub(filepath, filename)
                except Exception as e:
                    result = "Failed to sign manifest store: " + str(e)
            elif action == "manifest":
                try:
                    with open(filepath, "rb") as stream:
                        with Reader(
                            format_or_path="application/epub+zip", stream=stream
                        ) as reader:
                            manifest_json = reader.json()
                            manifest = json.loads(manifest_json)
                            active_manifest_key = manifest.get("active_manifest")
                            active_manifest = manifest["manifests"].get(
                                active_manifest_key, {}
                            )
                            json_result = active_manifest
                except Exception as err:
                    result = f"Error reading manifest: {str(err)}"
            elif action == "metadata":
                if ".epub" not in filename:
                    result = "Function only works for EPUB files."
                else:
                    try:
                        # Use exposed get_epub_metadata function
                        metadata = get_epub_metadata(filepath)
                        result = f"📚 EPUB Metadata for {filename}:\n{json.dumps(metadata, indent=2)}"
                        last_result["metadata"] = result
                        last_result["filename"] = filename
                        last_result["timestamp"] = datetime.now().strftime(
                            "%Y-%m-%d %H:%M:%S"
                        )
                    except Exception as err:
                        result = f"❌ Error reading EPUB metadata: {str(err)}"
            else:
                result = "Unknown action"
            return render_template(
                "index.html", filename=filename, result=result, json_result=json_result
            )
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
        "CustomTitle",
        parent=styles["Heading1"],
        fontSize=24,
        spaceAfter=30,
        alignment=1,  # Center alignment
    )
    story.append(Paragraph("EPUB C2PA Analysis Report", title_style))
    story.append(Spacer(1, 20))

    # File information
    file_info = [
        ["File Name:", last_result["filename"]],
        ["Analysis Date:", last_result["timestamp"]],
    ]

    file_table = Table(file_info, colWidths=[2 * inch, 4 * inch])
    file_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.grey),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.whitesmoke),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 12),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
                ("BACKGROUND", (1, 0), (1, -1), colors.beige),
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
            ]
        )
    )
    story.append(file_table)
    story.append(Spacer(1, 20))

    # Verification Result
    story.append(Paragraph("Verification Result", styles["Heading2"]))
    story.append(Spacer(1, 10))
    story.append(Paragraph(last_result["verify_result"], styles["Normal"]))
    story.append(Spacer(1, 20))

    # Metadata Result
    story.append(Paragraph("EPUB Metadata", styles["Heading2"]))
    story.append(Spacer(1, 10))

    # Format metadata for better display
    metadata_text = last_result["metadata"].replace(
        "📚 EPUB Metadata for " + last_result["filename"] + ":\n", ""
    )
    metadata_lines = metadata_text.split("\n")

    for line in metadata_lines:
        if line.strip():
            # Indent JSON content
            if line.startswith("  "):
                story.append(Paragraph(line, styles["Normal"]))
            else:
                story.append(Paragraph(line, styles["Normal"]))

    # Build PDF
    doc.build(story)

    return send_file(pdf_path, as_attachment=True, download_name=pdf_filename)


if __name__ == "__main__":
    app.run(debug=True)
