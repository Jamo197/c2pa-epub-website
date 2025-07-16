import json
import os

from c2pa import Reader
from flask import Flask, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = "uploads"
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)


@app.route("/", methods=["GET", "POST"])
def upload_file():
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
                result = f"Verified {filename}"
            elif action == "sign":
                result = f"Signed {filename}"
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
            else:
                result = "Unknown action"
            return render_template("index.html", filename=filename, result=result)
    return render_template("index.html")


if __name__ == "__main__":
    app.run(debug=True)
