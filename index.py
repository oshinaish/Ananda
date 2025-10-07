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

# --- CONFIGURATION: STORE DEMAND ITEM LIST (UPDATED FROM UPLOADED FILES) ---
# IMPORTANT: This list is compiled from the images you provided.
# Longer, more specific names are listed first for better matching accuracy.
KNOWN_STORE_DEMAND_ITEMS = sorted([
    # Prepared Food & Raw Materials
    'Kacha Peanut Chilke wala', 'Sarson (Mustard seed)', 'Pineapple Halwa', 'Filter Coffee Pow.', 'Whole red chilli', 
    'Fortune Refined', 'Roasted Peanuts', 'Roasted Chana', 'Red Chutney', 'Dosa Batter', 'Idli Batter', 
    'Vada Batter', 'Onion masala', 'Upma Sooji', 'Garlic Paste', 'Podi Masala', 'Dhania Whole', 
    'Staff Dal', 'Sarson Tel', 'Meetha Soda', 'Soya Badi', 'Chai Patti', 'Kali Mirch', 'Desi Ghee', 
    'Sambhar', 'Rawa mix', 'Sugar',
    'Milk', 'Rice', 'Atta', 'Jeera', 'Kaju', 'Poha', 'Besan', 'Achar', 'Chhole', 'Rajma', 
    'Chana Dal', 
    
    # Vegetables & Masala
    'Green Chillies(Hari Mirch)', 'Coriander leaves(Dhaniyan Patta)', 'Curry Leaves (Kari Patta)', 
    'Banana Leaves(Kela Patta)', 'Coconut Crush', 'Potato(aloo)', 'Mint(Pudina)', 'Staff Veg.', 
    'Deggi Mirch', 'Garam Masala', 'Hing Powder', 'Dhaniya Powder', 'Kitchen King', 'Chat Masala', 
    'Haldi Powder', 'Hari Ilaychi', 'Tata Salt', 'Black Salt', 'Onions', 'Tomatoes', 'Ginger', 
    'Carrot', 'Beans', 'Garlic', 'Lemon',
    
    # Disposal
    '50ML Container', '100ML Container', '250ML Container', '300ML Container', '500ML Container', 
    'Podi Idli Container', 'Silver lifafa', 'Vada Lifafa', 'Dosa Box Small', 'Dosa Box Big', 
    '16*20 Biopolythene', '13*16 Biopolythene', 'Bio Garbagebag Big Size', 'Printer Roll', 
    'Bio Spoon', 'Wooden Plates', 'Paper Bowl', 'Filter Coffee Glass', 'Masala Chhachh Glass', 
    'Filter Coffee Packaging', 'Masala Chhachh Packaging', 'Clean Wrap', 'Butter Paper', 'Delivery Bag',
    'Tape', 'Tissues', 'Chef Cap'
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
        match = re.search(r'(\d+\.?\d*)\s*([a-zA-Z]+)?', line, re.IGNORECASE) # Relaxed unit check
        
        if match:
            quantity = match.group(1)
            unit_candidate = match.group(2) if match.group(2) else ''

            if unit_candidate and unit_candidate.lower() in COMMON_UNITS:
                unit = unit_candidate
                # Recalculate item_name and notes based on the regex match position
                item_name = line[:match.start()].strip()
                notes = line[match.end():].strip()
            else:
                unit = ''
                # If no unit match, the unit candidate might be part of notes/size
                item_name = line[:match.start()].strip()
                notes = line[match.end():].strip()
                if unit_candidate:
                    notes = f"{unit_candidate} {notes}".strip()


        price_match = re.search(r'(Rs\.?|₹)\s*(\d+\.?\d*)', notes, re.IGNORECASE)
        if price_match:
            price = price_match.group(0)
            notes = notes.replace(price_match.group(0), '').strip()
            
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

# --- RECTIFIED PARSER 3: For Store Demand (Matching Logic) ---
def parse_store_demand_text(text):
    """
    Parses text into four columns: S. no., Item, Unit, Quantity using KNOWN_STORE_DEMAND_ITEMS for matching.
    """
    lines = text.strip().split('\n')
    parsed_items = []
    s_no = 1
    ignore_keywords = ['date', 'item', 'unit', 'quantity', 'demand', 's.no', 'sno']

    for line in lines:
        line_lower = line.lower().strip()
        if not line_lower or any(keyword in line_lower for keyword in ignore_keywords):
            continue
        
        # Remove leading S. no. if present
        cleaned_line = line.strip()
        if cleaned_line.split() and cleaned_line.split()[0].replace('.', '').isdigit():
             cleaned_line = " ".join(cleaned_line.split()[1:])
        
        # 1. Try to match a known item name (must be a whole word match)
        matched_item = None
        match_end_index = -1
        
        for item in KNOWN_STORE_DEMAND_ITEMS:
            # Look for the item name in the cleaned line
            item_lower = item.lower()
            if item_lower in cleaned_line.lower():
                # Ensure it's a whole word match or followed by numbers/units
                pattern = r'\b' + re.escape(item_lower) + r'\b'
                match = re.search(pattern, cleaned_line.lower())
                
                if match:
                    matched_item = item
                    # Calculate where the item name ends in the original cleaned_line
                    match_end_index = match.end() + (len(cleaned_line) - len(cleaned_line.lstrip()))
                    break
        
        if not matched_item:
            continue

        # 2. Get the part of the string AFTER the matched item
        remaining_text = cleaned_line[match_end_index:].strip()

        # 3. Extract Quantity and Unit from remaining_text
        quantity, unit = '', ''

        # Search for the quantity (number) and optional unit right before or after it
        # This regex looks for: (unit)? (quantity) or (quantity) (unit)?
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
            parsed_items.append([str(s_no), matched_item, unit, quantity])
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
            # Use the new dedicated parser and column headers
            columns, rows = [['S. no.', 'Item', 'Unit', 'Quantity']], parse_store_demand_text(extracted_text)
        else: # Fallback
            columns, rows = [['Date', 'Item', 'Unit', 'Quantity']], parse_simple_list_text(extracted_text)

        # Fallback to single column if no structured items were found
        if not rows and extracted_text:
            columns = [['Extracted Text']]
            rows = [[line] for line in extracted_text.strip().split('\n') if line.strip()]

        return jsonify({"columns": columns, "rows": rows})

    except Exception as e:
        return jsonify({"error": "An exception occurred during OCR", "details": str(e)}), 500

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
