# New api/index.py for Vercel
import os
import json
import base64
from flask import Flask, request, jsonify
from google.oauth2 import service_account
from googleapiclient.discovery import build
# We don't need the OCR part for the MVP, 
# as the goal is to get the image to the backend and update the sheet.
# In a real app, you would add Google Vision API calls here.

app = Flask(__name__)

@app.route('/api', methods=['POST'])
def handler():
    try:
        # Check if an image file is part of the request
        if 'image' not in request.files:
            return jsonify({"error": "No image file found in the request."}), 400
        
        image_file = request.files['image']
        # You can save or process the image_file here if needed in the future
        # For now, we just confirm it was received.

        # --- GOOGLE SHEETS LOGIC (same as before) ---
        SPREADSHEET_ID = 'YOUR_WORKING_SPREADSHEET_ID_HERE' 
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

        # Add a placeholder row to confirm the app connection
        data_to_add = [['Image received from Flutter App', 'Success', '24/09/2025']]
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

# This allows the app to be run locally for testing if needed
if __name__ == "__main__":
    app.run(debug=True)
