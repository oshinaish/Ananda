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

# --- PARSER 1: For Invoices (no changes) ---
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

# --- PARSER 2: For Simple Appends (Inventory Out) (no changes) ---
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
        quantity, quantity_index = '', -1
        for i, word in enumerate(words):
            if word.replace('.', '', 1).isdigit():
                quantity, quantity_index = word, i
                break
        if quantity_index == -1: continue
        unit, item_name_end_index = '', quantity_index
        if quantity_index > 0 and not words[quantity_index - 1].replace('.', '', 1).isdigit():
            unit, item_name_end_index = words[quantity_index - 1], quantity_index - 1
        item_name = " ".join(words[:item_name_end_index]).strip()
        if item_name:
             parsed_items.append([today_date, item_name, unit, quantity])
    return parsed_items

# --- NEW PARSER 3: For Store Demand (Rectified Logic) ---
def parse_store_demand_text(text):
    """
    Parses text into four columns: S. no., Item, Unit, Quantity.
    This is now an append operation, not an update.
    """
    lines = text.strip().split('\n')
    parsed_items = []
    s_no = 1
    ignore_keywords = ['date', 'item', 'unit', 'quantity', 'demand', 's.no', 'sno']
    # A set of common units to help with parsing
    common_units = {'kg', 'g', 'gm', 'ltr', 'lt', 'ml', 'pc', 'pcs', 'dozen', 'box', 'pkt', 'packet'}

    for line in lines:
        line_lower = line.lower()
        if not line.strip() or any(keyword in line_lower for keyword in ignore_keywords):
            continue
        
        words = line.strip().split()
        if words and words[0].replace('.', '').isdigit():
            words = words[1:]
        
        if len(words) < 1: continue

        quantity, quantity_index = '', -1
        for i in range(len(words) - 1, -1, -1):
            if words[i].replace('.','',1).isdigit():
                quantity, quantity_index = words[i], i
                break
        
        if quantity_index == -1: continue

        # --- Improved Unit and Item Name Logic ---
        unit = ''
        item_name = ''
        
        # Check if the word before the quantity is a known unit
        if quantity_index > 0 and words[quantity_index - 1].lower().rstrip('.') in common_units:
            unit = words[quantity_index - 1]
            item_name = " ".join(words[:quantity_index - 1]).strip()
        else:
            # If not a known unit, it's part of the item name
            unit = ''
            item_name = " ".join(words[:quantity_index]).strip()

        if item_name:
            parsed_items.append([str(s_no), item_name, unit, quantity])
            s_no += 1
            
    return parsed_items

# --- Endpoint 1 - OCR Handler (UPDATED to use new parser) ---
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

        columns, rows = [], []
        if "Purchases" in sheet_name:
            columns, rows = [['Item Name', 'Quantity', 'Unit', 'Notes/Size', 'Price']], parse_invoice_text(extracted_text)
        elif "Inventory" in sheet_name:
            columns, rows = [['Date', 'Item', 'Unit', 'Quantity']], parse_simple_list_text(extracted_text)
        elif "StoreDemand" in sheet_name:
            # RECTIFIED: Use the new dedicated parser and column headers
            columns, rows = [['S. no.', 'Item', 'Unit', 'Quantity']], parse_store_demand_text(extracted_text)
        else: # Fallback
            columns, rows = [['Date', 'Item', 'Unit', 'Quantity']], parse_simple_list_text(extracted_text)

        if not rows and extracted_text:
            columns = [['Extracted Text']]
            rows = [[line] for line in extracted_text.strip().split('\n') if line.strip()]

        return jsonify({"columns": columns, "rows": rows})

    except Exception as e:
        return jsonify({"error": "An exception occurred during OCR", "details": str(e)}), 500

# --- Endpoint 2 - Save Handler (UPDATED to handle new Store Demand format) ---
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

        is_fallback = len(rows_to_save[0]) == 1
        
        # RECTIFIED: The complex "update" logic for Store Demand has been removed.
        # It is now treated as a simple append operation like the others.
        header = []
        if is_fallback:
            header = [['Notes (Unparsed)']]
        elif "Purchases" in sheet_name:
            header = [['Item Name', 'Quantity', 'Unit', 'Notes/Size', 'Price']]
        elif "Inventory" in sheet_name:
            header = [['Date', 'Item', 'Unit', 'Quantity']]
        elif "StoreDemand" in sheet_name:
            header = [['S. no.', 'Item', 'Unit', 'Quantity']]

        data_to_add = header + rows_to_save
        body = {'values': data_to_add}
        service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{sheet_name}!A1",
            valueInputOption='USER_ENTERED',
            body=body
        ).execute()
        return jsonify({"message": f"✅ Success! {len(rows_to_save)} items saved to {sheet_name}."})

    except Exception as e:
        return jsonify({"error": "An exception occurred during save", "details": str(e)}), 500

# --- Health Check Route (no changes) ---
@app.route('/', methods=['GET'])
def health_check():
    return jsonify({"status": "ok", "message": "Backend is running!"})

