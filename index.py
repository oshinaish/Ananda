from flask import Flask, request, jsonify, abort

app = Flask(__name__)

# NOTE: This endpoint is set up to receive the image file but is not used
# by the latest frontend (index.html), which uses the Gemini API directly
# for OCR processing.

def parse_image_data(image_data, sheet_name):
    """
    Placeholder function to simulate image processing and return structured data.
    In a real-world application, this would use a dedicated OCR service.
    
    Args:
        image_data (bytes): The binary data of the uploaded image file.
        sheet_name (str): The name of the sheet (e.g., 'StoreDemand-23').

    Returns:
        dict: A dictionary containing 'columns' (headers) and 'rows' (data).
    """
    # Dummy data structure to match the frontend's expected JSON format (columns and rows)
    # The actual data extraction is now handled client-side by the agentOcr function in index.html.
    
    dummy_columns = [
        ["Item Name", "Quantity", "Unit", "Price"]
    ]
    
    # Return 2-3 dummy rows based on the sheet name
    if 'StoreDemand' in sheet_name:
        dummy_rows = [
            ["Chicken Breast", "15", "kg", "2.5"],
            ["Potatoes", "50", "kg", "0.75"],
            ["Lettuce", "30", "units", "1.20"]
        ]
    elif 'Purchases' in sheet_name:
        dummy_rows = [
            ["Cooking Oil", "20", "liters", "50.00"],
            ["Salt (Iodized)", "5", "kg", "3.50"]
        ]
    elif 'Inventory' in sheet_name:
         dummy_rows = [
            ["Tomato Sauce", "10", "jars", "4.00"],
            ["Flour (AP)", "40", "kg", "0.80"]
        ]
    else:
        dummy_rows = []

    return {
        "columns": dummy_columns,
        "rows": dummy_rows
    }

@app.route('/api/ocr', methods=['POST'])
def ocr_handler():
    """Handles image upload, extraction, and returns structured data."""
    if 'image' not in request.files:
        return jsonify({"details": "No image file provided"}), 400

    file = request.files['image']
    sheet_name = request.form.get('sheetName', 'Unknown')
    
    # Read image data
    image_data = file.read()

    try:
        # NOTE: In the current setup, this function is only a placeholder
        # as the frontend is calling the AI directly.
        data = parse_image_data(image_data, sheet_name)
        return jsonify(data)
    except Exception as e:
        # In case of an OCR processing error
        return jsonify({"details": f"Internal OCR Processing Error: {str(e)}"}), 500

@app.route('/api/save', methods=['POST'])
def save_handler():
    """Simulates saving the confirmed data."""
    try:
        data = request.json
        sheet_name = data.get('sheetName', 'Unknown')
        
        # In a real app, this is where you would save to Firestore or a database.
        # This is a simulation for demonstration.
        
        if not data.get('data'):
             return jsonify({"message": "No data received to save."}), 400
             
        return jsonify({
            "message": f"Success! Data with {len(data['data'])} rows received and simulated saved to {sheet_name}."
        })
    except Exception as e:
        return jsonify({"details": f"Save operation failed: {str(e)}"}), 500

if __name__ == '__main__':
    # This block is for local testing and may not run in the final deployment environment.
    app.run(debug=True)
