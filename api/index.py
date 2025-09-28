# New api/index.py for Vercel
import os
import json
import base64
from flask import Flask, request, jsonify
from flask_cors import CORS # Import CORS
from google.oauth2 import service_account
from googleapiclient.discovery import build

app = Flask(__name__)
CORS(app) # Enable CORS for all routes

@app.route('/api', methods=['POST'])
def handler():
    try:
        if 'image' not in request.files:
            return jsonify({"error": "No image file found in the request."}), 400
        
        image_file = request.files['image']
        
        # --- GOOGLE SHEETS LOGIC ---
        SPREADSHEET_ID = os.environ.get('SPREADSHEET_ID')
        if not SPREADSHEET_ID:
            return jsonify({"error": "SPREADSHEET_ID environment variable not set."}), 500

        SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
        WORKSHEET_NAME = 'Sheet1' 

        creds_json_b64 = os.environ.get('GOOGLE_CREDENTIALS_BASE64')
        if not creds_json_b64:
            return jsonify({"error": "Credentials not found."}), 500
        
        creds_json_str = base64.b64decode(creds_json_b64).decode('utf-8')
        creds_info = json.loads(creds_json_str)
        creds = service_account.Credentials.from_service_account_info(creds_info, scopes=SCOPES)
        
        service = build('sheets', 'v4', credentials=creds)
        sheet = service.spreadsheets()

        data_to_add = [['Image received from PWA', 'Success!', '28/09/2025']]
        request_body = {'values': data_to_add}

        result = sheet.values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{WORKSHEET_NAME}!A1",
            valueInputOption='USER_ENTERED',
            body=request_body
        ).execute()

        return jsonify({"message": "✅ Success! Image received and Sheet updated."})

    except Exception as e:
        return jsonify({"error": "An exception occurred", "details": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True)
