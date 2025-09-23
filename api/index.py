import os
import json
import base64
from flask import Flask, jsonify
from google.oauth2 import service_account
from googleapiclient.discovery import build

app = Flask(__name__)

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>', methods=['GET'])
def handler(path):
    try:
        # --- CONFIGURATION ---
        # IMPORTANT: Replace this with the ID of your working Google Sheet
        SPREADSHEET_ID = '1YwDAnxU4-LzY5TCIR6LRjrtYjEIc1Sk6SNG3jmiID_g' 
        
        SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
        WORKSHEET_NAME = 'Purchases'

        # --- SECURELY LOAD CREDENTIALS FROM VERCEL ENVIRONMENT VARIABLE ---
        creds_json_b64 = os.environ.get('GOOGLE_CREDENTIALS_BASE64')
        if not creds_json_b64:
            return jsonify({"error": "GOOGLE_CREDENTIALS_BASE64 environment variable not found."}), 500
        
        creds_json_str = base64.b64decode(creds_json_b64).decode('utf-8')
        creds_info = json.loads(creds_json_str)
        creds = service_account.Credentials.from_service_account_info(creds_info, scopes=SCOPES)
        
        # --- GOOGLE SHEETS LOGIC ---
        service = build('sheets', 'v4', credentials=creds)
        sheet = service.spreadsheets()

        data_to_add = [['Vercel Deployment Test', 'This entry was added at 8:05 PM IST on Sep 23, 2025']]
        request_body = {'values': data_to_add}

        result = sheet.values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{WORKSHEET_NAME}!A1",
            valueInputOption='USER_ENTERED',
            body=request_body
        ).execute()

        return jsonify({
            "message": "✅ Success! The Google Sheet was updated.",
            "updatedCells": result.get('updates').get('updatedCells')
        })

    except Exception as e:
        # Provide a detailed error message for easier debugging
        return jsonify({"error": "An exception occurred", "details": str(e)}), 500
