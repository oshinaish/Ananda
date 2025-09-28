# Main Python file (index.py) for Vercel
import os
import json
import base64
from flask import Flask, request, jsonify
from flask_cors import CORS
from google.oauth2 import service_account
from googleapiclient.discovery import build
# --- NEW: Import Google Cloud Vision client library ---
from google.cloud import vision

app = Flask(__name__)
CORS(app)

# --- Function to get Google API credentials ---
def get_google_creds():
    creds_json_b64 = os.environ.get('GOOGLE_CREDENTIALS_BASE64')
    if not creds_json_b64:
        raise ValueError("GOOGLE_CREDENTIALS_BASE64 environment variable not found.")
    
    creds_json_str = base64.b64decode(creds_json_b64).decode('utf-8')
    return json.loads(creds_json_str)

# --- DEBUGGING ROUTE ---
@app.route('/api', methods=['GET'])
def ping_handler():
    return jsonify({"status": "ok", "message": "Backend is running and ready for OCR!"})

# --- UPLOAD ROUTE (UPGRADED WITH OCR) ---
@app.route('/api', methods=['POST'])
def upload_handler():
    try:
        if 'image' not in request.files:
            return jsonify({"error": "No image file found in the request."}), 400
        
        image_file = request.files['image']
        image_content = image_file.read() # Read image content as bytes

        # --- STEP 1: OCR with Google Cloud Vision ---
        creds_info = get_google_creds()
        vision_credentials = service_account.Credentials.from_service_account_info(creds_info)
        vision_client = vision.ImageAnnotatorClient(credentials=vision_credentials)

        image = vision.Image(content=image_content)
        response = vision_client.text_detection(image=image)
        texts = response.text_annotations
        
        extracted_text = ""
        if texts:
            # The first text annotation contains the full block of text
            extracted_text = texts[0].description
        
        if response.error.message:
            raise Exception(f"Google Vision API Error: {response.error.message}")

        # --- STEP 2: Write a confirmation to Google Sheets ---
        SPREADSHEET_ID = os.environ.get('SPREADSHEET_ID')
        if not SPREADSHEET_ID:
            raise ValueError("SPREADSHEET_ID environment variable not set.")
        
        sheets_credentials = service_account.Credentials.from_service_account_info(creds_info, scopes=['https://www.googleapis.com/auth/spreadsheets'])
        service = build('sheets', 'v4', credentials=sheets_credentials)
        sheet = service.spreadsheets()

        data_to_add = [['OCR Success', 'Text Extracted Successfully', '28/09/2025']]
        request_body = {'values': data_to_add}

        sheet.values().append(
            spreadsheetId=SPREADSHEET_ID,
            range='Sheet1!A1',
            valueInputOption='USER_ENTERED',
            body=request_body
        ).execute()
        
        # --- STEP 3: Return the extracted text to the PWA ---
        return jsonify({
            "message": "✅ Success! Text extracted.",
            "extractedText": extracted_text
        })

    except Exception as e:
        return jsonify({"error": "An exception occurred", "details": str(e)}), 500

