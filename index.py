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

# --- CONFIGURATION: STORE DEMAND ITEM LIST (FOCUSED FOR ACCURATE PARSING) ---
# This list is exhaustive and sorted by length (longest first) to ensure the OCR
# parser matches the most specific item name possible.
KNOWN_STORE_DEMAND_ITEMS = sorted([
    'Coriander leaves(Dhaniyan Patta)', 'Green Chillies(Hari Mirch)', 'Banana Leaves(Kela Patta)',
    'Curry Leaves (Kari Patta)', 'Bio Garbagebag Big Size', 'Masala Chhachh Packaging',
    'Filter Coffee Packaging', 'Kacha Peanut Chilke wala', 'Masala Chhachh Glass',
    '13*16 Biopolythene', '16*20 Biopolythene', 'Filter Coffee Glass', 'Podi Idli Container',
    'Sarson (Mustard seed)', '500ML Container', '300ML Container', '250ML Container',
    '100ML Container', 'Pineapple Halwa', 'Whole red chilli', 'Fortune Refined',
    'Roasted Peanuts', '50ML Container', 'Butter Paper', 'Dhaniya Powder', 'Roasted Chana',
    'Delivery Bag', 'Garlic Paste', 'Hari Ilaychi', 'Kitchen King', 'Mint(Pudina)',
    'Onion masala', 'Potato(aloo)', 'Chat Masala', 'Deggi Mirch', 'Garam Masala',
    'Haldi Powder', 'Hing Powder', 'Vada Batter', 'Red Chutney', 'Bio Spoon',
    'Dosa Batter', 'Idli Batter', 'Upma Sooji', 'Clean Wrap', 'Staff Veg.',
    'Dosa Box Small', 'Dosa Box Big', 'Filter Coffee Pow.', 'Vada Lifafa',
    'Coconut Crush', 'Silver lifafa', 'Podi Masala', 'Dhania Whole', 'Sarson Tel',
    'Meetha Soda', 'Chana Dal', 'Tata Salt', 'Black Salt', 'Chai Patti',
    'Staff Dal', 'Soya Badi', 'Desi Ghee', 'Sambhar', 'Rawa mix', 'Tomatoes',
    'Capsicum', 'Cabbage', 'Printer Roll', 'Chef Cap', 'Paper Bowl', 'Chhole',
    'Ginger', 'Garlic', 'Carrot', 'Onions', 'Tissues', 'Wooden Plates', 'Paneer',
    'Sugar', 'Achar', 'Besan', 'Rajma', 'Lemon', 'Pouch', 'Maida', 'Jeera',
    'Milk', 'Rice', 'Atta', 'Kaju', 'Poha', 'Salt', 'Tape', 'Eggs'
], key=len, reverse=True)


# A set of common units for parsing (Updated to include 'Batch' and common short forms)
COMMON_UNITS = {'kg', 'g', 'gm', 'ltr', 'lt', 'ml', 'pc', 'pcs', 'dozen', 'box', 'pkt', 'packet', 'tin', 'bag', 'Batch', 'batch', 'pieces', 'bundle'}


# --- Function to get Google API credentials (no changes) ---
def get_google_creds():
    creds_json_b64 = os.environ.get('GOOGLE_CREDENTIALS_BASE64')
    if not creds_json_b64:
        raise ValueError("GOOGLE_CREDENTIALS_BASE64 environment variable not found.")
    
    creds_json_str = base64.b64decode(creds_json_b64).decode('utf-8')
    return json.loads(creds_json_str)


# --- FOCUSED PARSER: For Store Demand (Matching Logic) ---
def parse_store_demand_text(text):
    """
    Parses text into four columns: S. no., Item, Unit, Quantity using KNOWN_STORE_DEMAND_ITEMS for matching.
    """
    lines = text.strip().split('\n')
    parsed_items = []
    s_no = 1
    ignore_keywords = ['date', 'item', 'unit', 'quantity', 'demand', 's.no', 'sno', 'outlet']

    for line in lines:
        line_lower = line.lower().strip()
        if not line_lower or any(keyword in line_lower for keyword in ignore_keywords):
            continue
        
        # Remove potential leading serial numbers (e.g., "1.", "2 ", "3-")
        cleaned_line = line.strip()
        if cleaned_line.split() and cleaned_line.split()[0].replace('.', '').replace('-', '').isdigit():
             cleaned_line = " ".join(cleaned_line.split()[1:])
        
        # 1. Try to match a known item name (must be a whole word match)
        matched_item = None
        match_end_index = -1
        
        for item in KNOWN_STORE_DEMAND_ITEMS:
            item_lower = item.lower()
            
            # Use regex to find the item name as a whole word
            pattern = r'\b' + re.escape(item_lower) + r'\b'
            match = re.search(pattern, cleaned_line.lower())
            
            if match:
                matched_item = item
                # Get the index in the original cleaned_line where the item name ends
                match_end_index = match.end() 
                break # Found the best match (since list is sorted longest first)
        
        if not matched_item:
            continue

        # 2. Get the part of the string AFTER the matched item
        remaining_text = cleaned_line[match_end_index:].strip()

        # 3. Extract Quantity and Unit from remaining_text
        quantity, unit = '', ''

        # This regex is specifically tuned to find the number (quantity) and an optional unit
        # either before or after it, in the remaining text.
        # Example remaining_text: " 5 kg" or "kg 5" or "5"
        match = re.search(r'(([a-zA-Z]+)\s*)?(\d+\.?\d*)\s*([a-zA-Z]+)?', remaining_text, re.IGNORECASE)
        
        if match:
            # Group 3 is always the quantity (number)
            quantity = match.group(3)
            
            # Check Group 2 (unit before quantity)
            unit_before = match.group(2)
            if unit_before and unit_before.lower() in COMMON_UNITS:
                unit = unit_before
            
            # Check Group 4 (unit after quantity)
            unit_after = match.group(4)
            if unit_after and unit_after.lower() in COMMON_UNITS:
                unit = unit_after

        if quantity:
            # If the quantity is found, we log the complete, clean item name
            parsed_items.append([str(s_no), matched_item, unit, quantity])
            s_no += 1
            
    return parsed_items

# --- Endpoint 1 - OCR Handler (FOCUSED on Store Demand) ---
@app.route('/api/ocr', methods=['POST'])
def ocr_handler():
    try:
        if 'image' not in request.files: return jsonify({"error": "No image file found."}), 400
        
        sheet_name = request.form.get('sheetName', '')
        image_content = request.files['image'].read()
        
        creds_info = get_google_creds()
        vision_credentials = service_account.Credentials.from_service_account_info(creds_info)
        vision_client = vision.ImageAnnotatorClient(credentials=vision_credentials)
        
        # Use DOCUMENT_TEXT_DETECTION for better structure preservation
        response = vision_client.document_text_detection(image=vision.Image(content=image_content))
        if response.error.message: raise Exception(f"Google Vision API Error: {response.error.message}")
        
        extracted_text = response.text_annotations[0].description if response.text_annotations else ""

        columns, rows = [], []
        
        # This implementation ONLY handles StoreDemand logic.
        if "StoreDemand" in sheet_name:
            columns, rows = [['S. no.', 'Item', 'Unit', 'Quantity']], parse_store_demand_text(extracted_text)
        else: 
             # Fallback: if user uploads something else, treat it as unparsed text for review
            columns = [['Extracted Text']]
            rows = [[line] for line in extracted_text.strip().split('\n') if line.strip()]

        # Fallback to single column if no structured items were found, but text was extracted
        if not rows and extracted_text:
            columns = [['Extracted Text']]
            rows = [[line] for line in extracted_text.strip().split('\n') if line.strip()]

        return jsonify({"columns": columns, "rows": rows})

    except Exception as e:
        # Provide more details for debugging
        error_details = {"error": "An exception occurred during OCR", "details": str(e)}
        if 'extracted_text' in locals():
            error_details["extracted_text"] = extracted_text
        return jsonify(error_details), 500

# --- Endpoint 2 - Save Handler (handles all appends) ---
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
        
        header = []
        if is_fallback:
            header = [['Notes (Unparsed)']]
        elif "StoreDemand" in sheet_name:
            header = [['S. no.', 'Item', 'Unit', 'Quantity']]
        # Removed headers for Purchases and Inventory

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
