# Main Python file (index.py) for Vercel
import os
import json
import base64
from flask import Flask, request, jsonify
from flask_cors import CORS
from google.oauth2 import service_account
from googleapiclient.discovery import build
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

# --- Endpoint 1 - Perform OCR and return text (No changes needed here) ---
@app.route('/api/ocr', methods=['POST'])
def ocr_handler():
    try:
        if 'image' not in request.files:
            return jsonify({"error": "No image file found."}), 400
        
        image_file = request.files['image']
        image_content = image_file.read()

        creds_info = get_google_creds()
        vision_credentials = service_account.Credentials.from_service_account_info(creds_info)
        vision_client = vision.ImageAnnotatorClient(credentials=vision_credentials)
        image = vision.Image(content=image_content)
        
        response = vision_client.document_text_detection(image=image)
        texts = response.text_annotations
        
        extracted_text = "No text found."
        if texts:
            extracted_text = texts[0].description
        if response.error.message:
            raise Exception(f"Google Vision API Error: {response.error.message}")

        return jsonify({
            "message": "✅ Success! Text extracted.",
            "extractedText": extracted_text
        })

    except Exception as e:
        return jsonify({"error": "An exception occurred during OCR", "details": str(e)}), 500


# --- Endpoint 2 - Receive corrected text and save to Sheets (UPDATED LOGIC) ---
@app.route('/api/save', methods=['POST'])
def save_handler():
    try:
        data = request.get_json()
        # **FIX**: Get both text and the sheetName from the request
        corrected_text = data.get('text')
        sheet_name = data.get('sheetName')

        if not corrected_text or not sheet_name:
            return jsonify({"error": "Text or sheetName not provided in the request."}), 400

        # --- Write to Google Sheets ---
        SPREADSHEET_ID = os.environ.get('SPREADSHEET_ID')
        if not SPREADSHEET_ID:
            raise ValueError("SPREADSHEET_ID environment variable not set.")
        
        creds_info = get_google_creds()
        sheets_credentials = service_account.Credentials.from_service_account_info(creds_info, scopes=['https://www.googleapis.com/auth/spreadsheets'])
        service = build('sheets', 'v4', credentials=sheets_credentials)
        sheet = service.spreadsheets()
        
        # **FIX**: Use the dynamic sheet_name from the frontend in the range
        range_to_update = f"{sheet_name}!A1"

        data_to_add = [['Final Data Saved', corrected_text[:25000], '30/09/2025']] # Increased character limit
        request_body = {'values': data_to_add}
        sheet.values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=range_to_update,
            valueInputOption='USER_ENTERED',
            body=request_body
        ).execute()
        
        return jsonify({"message": f"✅ Success! Data saved to {sheet_name}."})

    except Exception as e:
        return jsonify({"error": "An exception occurred during save", "details": str(e)}), 500

# --- Health Check Route (no changes) ---
@app.route('/', methods=['GET'])
def health_check():
    return jsonify({"status": "ok", "message": "Backend is running!"})

