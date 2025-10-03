# Main Python file (index.py) for Vercel
import os
import json
import base64
import re
from datetime import date
from flask import Flask, request, jsonify
from flask_cors import CORS
from google.oauth2 import service_account
from googleapiclient.discovery import build
from google.cloud import vision

app = Flask(__name__)
CORS(app)

# --- Function to get Google API credentials (no changes) ---
def get_google_creds():
    creds_json_b64 = os.environ.get('GOOGLE_CREDENTIALS_BASE64')
    if not creds_json_b64:
        raise ValueError("GOOGLE_CREDENTIALS_BASE64 environment variable not found.")
    
    creds_json_str = base64.b64decode(creds_json_b64).decode('utf-8')
    return json.loads(creds_json_str)

# --- PARSER 1: For Invoices ---
def parse_invoice_text(text):
    lines = text.strip().split('\n')
    parsed_items = []
    header_keywords = ['invoice', 'bill', 'receipt', 'date', 'total', 'gst', 'amount', 'item', 'qty', 'hsn']
    for line in lines:
        line_lower = line.lower()
        if not line.strip() or any(keyword in line_lower for keyword in header_keywords) or not any(char.isdigit() for char in line):
            continue
        item_name, quantity, unit, notes, price = line, '', '', '', ''
        match = re.search(r'(\d+\.?\d*)\s*(kg|g|gm|ltr|ml|pc|pcs|dozen|box)\b', line, re.IGNORECASE)
        if match:
            quantity, unit, item_name, notes = match.group(1), match.group(2), line[:match.start()].strip(), line[match.end():].strip()
        else:
            match = re.search(r'\d+\.?\d*', line)
            if match:
                quantity, item_name, notes = match.group(0), line[:match.start()].strip(), line[match.end():].strip()
        price_match = re.search(r'(Rs\.?|₹)\s*(\d+\.?\d*)', notes, re.IGNORECASE)
        if price_match:
            price, notes = price_match.group(0), notes.replace(price_match.group(0), '').strip()
        parsed_items.append([item_name, quantity, unit, notes, price])
    return parsed_items

# --- PARSER 2: For Simple Appends (Inventory Out) ---
def parse_simple_list_text(text):
    lines = text.strip().split('\n')
    parsed_items = []
    today_date = date.today().strftime("%Y-%m-%d")
    ignore_keywords = ['date', 'item', 'unit', 'quantity', 'inventory', 'out']
    for line in lines:
        line_lower = line.lower()
        if not line.strip() or any(keyword in line_lower for keyword in ignore_keywords):
            continue
        words = line.strip().split()
        if len(words) < 2: continue
        quantity = words[-1]
        if not quantity.replace('.','',1).isdigit(): continue
        unit, item_name = (words[-2], " ".join(words[:-2])) if len(words) > 2 else ('', " ".join(words[:-1]))
        parsed_items.append([today_date, item_name, unit, quantity])
    return parsed_items

# --- PARSER 3: For Store Demand (Update Logic) ---
def parse_update_list_text(text):
    lines = text.strip().split('\n')
    parsed_items = []
    today_date = date.today().strftime("%Y-%m-%d")
    ignore_keywords = ['date', 'item', 'unit', 'quantity', 'size', 'type', 'notes', 'demand']
    for line in lines:
        line_lower = line.lower()
        if not line.strip() or any(keyword in line_lower for keyword in ignore_keywords): continue
        words = line.strip().split()
        if len(words) < 2: continue
        quantity, quantity_index = '', -1
        for i, word in enumerate(words):
            if word.replace('.', '', 1).isdigit():
                quantity, quantity_index = word, i
                break
        if quantity_index == -1: continue
        item_name = " ".join(words[:quantity_index]).strip()
        notes = " ".join(words[quantity_index+1:]).strip()
        # Returns a list of lists for consistency
        parsed_items.append([today_date, item_name, '', quantity, '', notes]) # Date, Item, Unit, Qty, Size/Type, Notes
    return parsed_items

# --- Function to handle the sheet update logic (no changes) ---
def update_sheet_data(service, spreadsheet_id, sheet_name, parsed_items):
    range_to_read = f"{sheet_name}!B:B"
    result = service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=range_to_read).execute()
    existing_items = result.get('values', [])
    item_to_row_map = {item[0].strip().lower(): i + 1 for i, item in enumerate(existing_items) if item}
    
    data_for_update, updated_item_count = [], 0

    for item in parsed_items:
        # Assumes item format is [Date, Item, Unit, Qty, Size/Type, Notes]
        item_name_lower = item[1].lower() 
        if item_name_lower in item_to_row_map:
            row_number = item_to_row_map[item_name_lower]
            updated_item_count += 1
            data_for_update.append({'range': f"{sheet_name}!A{row_number}", 'values': [[item[0]]]}) # Date
            data_for_update.append({'range': f"{sheet_name}!D{row_number}", 'values': [[item[3]]]}) # Quantity
            data_for_update.append({'range': f"{sheet_name}!F{row_number}", 'values': [[item[5]]]}) # Notes
            
    if not data_for_update: return 0

    body = {'valueInputOption': 'USER_ENTERED', 'data': data_for_update}
    service.spreadsheets().values().batchUpdate(spreadsheetId=spreadsheet_id, body=body).execute()
    return updated_item_count

# --- Endpoint 1 - OCR Handler (UPDATED to parse text) ---
@app.route('/api/ocr', methods=['POST'])
def ocr_handler():
    try:
        if 'image' not in request.files: return jsonify({"error": "No image file found."}), 400
        
        sheet_name = request.form.get('sheetName', '')
        image_content = request.files['image'].read()
        
        creds_info = get_google_creds()
        vision_credentials = service_account.Credentials.from_service_account_info(creds_info)
        vision_client = vision.ImageAnnotatorClient(credentials=vision_credentials)
        response = vision_client.document_text_detection(image=vision.Image(content=image_content))
        if response.error.message: raise Exception(f"Google Vision API Error: {response.error.message}")
        
        extracted_text = response.text_annotations[0].description if response.text_annotations else ""

        # --- NEW: Parse text immediately and send back structured data ---
        columns, rows = [], []
        if "Purchases" in sheet_name:
            columns, rows = [['Item Name', 'Quantity', 'Unit', 'Notes/Size', 'Price']], parse_invoice_text(extracted_text)
        elif "Inventory" in sheet_name:
            columns, rows = [['Date', 'Item', 'Unit', 'Quantity']], parse_simple_list_text(extracted_text)
        elif "StoreDemand" in sheet_name:
            columns, rows = [['Date', 'Item', 'Unit', 'Quantity', 'Size/Type', 'Notes']], parse_update_list_text(extracted_text)
        else: # Default fallback
            columns, rows = [['Date', 'Item', 'Unit', 'Quantity']], parse_simple_list_text(extracted_text)

        return jsonify({"columns": columns, "rows": rows})

    except Exception as e:
        return jsonify({"error": "An exception occurred during OCR", "details": str(e)}), 500

# --- Endpoint 2 - Save Handler (UPDATED to accept structured data) ---
@app.route('/api/save', methods=['POST'])
def save_handler():
    try:
        data = request.get_json()
        sheet_name, rows_to_save = data.get('sheetName'), data.get('data')
        if not rows_to_save or not sheet_name: return jsonify({"error": "Data or sheetName not provided."}), 400
        
        creds_info = get_google_creds()
        sheets_credentials = service_account.Credentials.from_service_account_info(creds_info, scopes=['https://www.googleapis.com/auth/spreadsheets'])
        service = build('sheets', 'v4', credentials=sheets_credentials)
        SPREADSHEET_ID = os.environ.get('SPREADSHEET_ID')
        if not SPREADSHEET_ID: raise ValueError("SPREADSHEET_ID environment variable not set.")

        # --- INTELLIGENT PARSING AND SAVING ---
        if "StoreDemand" in sheet_name:
            # Reformat rows for update function
            update_data = [{"name": row[1], "quantity": row[3], "notes": row[5]} for row in rows_to_save]
            updated_count = update_sheet_data(service, SPREADSHEET_ID, sheet_name, update_data)
            return jsonify({"message": f"✅ Success! {updated_count} items updated in {sheet_name}."})
        else: # Handle Purchases and Inventory Out with append logic
            header = []
            if "Purchases" in sheet_name:
                header = [['Item Name', 'Quantity', 'Unit', 'Notes/Size', 'Price']]
            elif "Inventory" in sheet_name:
                header = [['Date', 'Item', 'Unit', 'Quantity']]
            
            data_to_add = header + rows_to_save
            body = {'values': data_to_add}
            service.spreadsheets().values().append(spreadsheetId=SPREADSHEET_ID, range=f"{sheet_name}!A1", valueInputOption='USER_ENTERED', body=body).execute()
            return jsonify({"message": f"✅ Success! {len(rows_to_save)} items saved to {sheet_name}."})

    except Exception as e:
        return jsonify({"error": "An exception occurred during save", "details": str(e)}), 500

# --- Health Check Route (no changes) ---
@app.route('/', methods=['GET'])
def health_check():
    return jsonify({"status": "ok", "message": "Backend is running!"})

