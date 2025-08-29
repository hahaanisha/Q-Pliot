from flask import Flask, request, jsonify
import gspread
from google.oauth2 import service_account
import os
import json
import re
import math
from urllib.parse import urlparse, parse_qs, unquote

app = Flask(__name__)

# Google Sheets setup - Works both locally and on Render
try:
    # Try environment variable first (for production/Render)
    creds_json = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    if creds_json:
        creds_dict = json.loads(creds_json)
        creds = service_account.Credentials.from_service_account_info(creds_dict, scopes=[
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive",
        ])
    else:
        # Fallback to local file (for testing)
        creds = service_account.Credentials.from_service_account_file(
            'cred.json', 
            scopes=[
                "https://spreadsheets.google.com/feeds",
                "https://www.googleapis.com/auth/drive",
            ]
        )
    client = gspread.authorize(creds)
    print("✅ Google Sheets connected successfully!")
except Exception as e:
    print(f"❌ Error connecting to Google Sheets: {str(e)}")
    raise

# Replace with your actual spreadsheet ID
SPREADSHEET_ID = "17cOylW-cc5fKKzHhyknUqwJCOuhwEJkjifVyh8WN5l8"
SHEET_NAME = "Location"

def extract_coordinates_from_url(url):
    """Extract latitude and longitude from various Google Maps URL formats"""
    try:
        # Decode URL if it's encoded
        url = unquote(url)
        print(f"Debug - Processing URL: {url}")
        
        # Method 1: Look for pb parameter (embed URLs)
        if 'pb=' in url:
            pb_match = re.search(r'pb=([^&]+)', url)
            if pb_match:
                pb_data = unquote(pb_match.group(1))
                print(f"Debug - PB data: {pb_data}")
                
                # Look for coordinates pattern in pb data - more flexible
                coord_patterns = [
                    r'!3d(-?\d+\.?\d*)!4d(-?\d+\.?\d*)',  # Original pattern
                    r'3d(-?\d+\.?\d*).*?4d(-?\d+\.?\d*)',  # Without !
                    r'!2d(-?\d+\.?\d*)!3d(-?\d+\.?\d*)',  # Alternative pattern
                ]
                
                for pattern in coord_patterns:
                    coord_match = re.search(pattern, pb_data)
                    if coord_match:
                        lat = float(coord_match.group(1))
                        lng = float(coord_match.group(2))
                        print(f"Debug - Found coordinates: {lat}, {lng}")
                        return lat, lng
        
        # Method 2: Look for @lat,lng pattern (regular Google Maps URLs)
        at_pattern = r'@(-?\d+\.?\d*),(-?\d+\.?\d*)'
        at_match = re.search(at_pattern, url)
        if at_match:
            lat = float(at_match.group(1))
            lng = float(at_match.group(2))
            print(f"Debug - Found coordinates via @ pattern: {lat}, {lng}")
            return lat, lng
        
        # Method 3: Look for direct coordinate patterns in the URL
        direct_patterns = [
            r'(-?\d+\.?\d+),(-?\d+\.?\d+)',  # Simple lat,lng
            r'll=(-?\d+\.?\d*),(-?\d+\.?\d*)',  # ll parameter
            r'center=(-?\d+\.?\d*),(-?\d+\.?\d*)',  # center parameter
        ]
        
        for pattern in direct_patterns:
            match = re.search(pattern, url)
            if match:
                lat = float(match.group(1))
                lng = float(match.group(2))
                # Basic validation for reasonable coordinates
                if -90 <= lat <= 90 and -180 <= lng <= 180:
                    print(f"Debug - Found coordinates via direct pattern: {lat}, {lng}")
                    return lat, lng
        
        print("Debug - No coordinates found")
        return None, None
    except Exception as e:
        print(f"Error extracting coordinates: {str(e)}")
        return None, None

def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculate the great circle distance between two points on earth in kilometers"""
    # Convert decimal degrees to radians
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    
    # Haversine formula
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    
    # Radius of earth in kilometers
    r = 6371
    return c * r

def find_nearest_station(user_lat, user_lng, stations_data):
    """Find the nearest station based on haversine distance"""
    min_distance = float('inf')
    nearest_station = None
    
    for station in stations_data:
        try:
            station_lat = float(station['Latitude'])
            station_lng = float(station['Longitude'])
            
            distance = haversine_distance(user_lat, user_lng, station_lat, station_lng)
            
            if distance < min_distance:
                min_distance = distance
                nearest_station = {
                    'station': station['Station'],
                    'latitude': station_lat,
                    'longitude': station_lng,
                    'url': station['URL'],
                    'distance_km': round(distance, 2)
                }
        except (ValueError, KeyError) as e:
            print(f"Error processing station data: {station}, error: {str(e)}")
            continue
    
    return nearest_station

@app.route("/debug_url", methods=["GET"])
def debug_url():
    """Debug endpoint to test URL parsing"""
    maps_url = request.args.get("url")
    
    if not maps_url:
        return jsonify({"error": "Please provide a URL parameter"}), 400
    
    # Extract coordinates from the URL
    user_lat, user_lng = extract_coordinates_from_url(maps_url)
    
    return jsonify({
        "input_url": maps_url,
        "decoded_url": unquote(maps_url),
        "extracted_latitude": user_lat,
        "extracted_longitude": user_lng,
        "success": user_lat is not None and user_lng is not None
    })

@app.route("/nearest_station", methods=["GET"])
def nearest_station():
    """API endpoint to find nearest station from latitude and longitude"""
    lat_param = request.args.get("lat")
    lng_param = request.args.get("lng")
    
    if not lat_param or not lng_param:
        return jsonify({"error": "Please provide both 'lat' and 'lng' parameters"}), 400
    
    try:
        user_lat = float(lat_param)
        user_lng = float(lng_param)
        
        # Basic validation for reasonable coordinates
        if not (-90 <= user_lat <= 90) or not (-180 <= user_lng <= 180):
            return jsonify({"error": "Invalid coordinates. Latitude must be between -90 and 90, longitude between -180 and 180"}), 400
            
    except ValueError:
        return jsonify({"error": "Invalid coordinate format. Please provide numeric values for lat and lng"}), 400
    
    try:
        # Access the Google Sheet
        spreadsheet = client.open_by_key(SPREADSHEET_ID)
        sheet = spreadsheet.worksheet(SHEET_NAME)
        
        # Get all data from the sheet
        data = sheet.get_all_records()
        
        if not data:
            return jsonify({"error": "No station data found in the sheet"}), 404
        
        # Find the nearest station
        nearest = find_nearest_station(user_lat, user_lng, data)
        
        if not nearest:
            return jsonify({"error": "Could not find any valid stations"}), 404
        
        # Return response in the requested format
        response = {
            "distance_km": nearest['distance_km'],
            "latitude": nearest['latitude'],
            "longitude": nearest['longitude'],
            "nearest_station": nearest['station'],
            "url": nearest['url']
        }
        
        return jsonify(response)
        
    except Exception as e:
        return jsonify({"error": f"Could not access sheet data: {str(e)}"}), 500

@app.route("/health", methods=["GET"])
def health_check():
    """Simple health check endpoint"""
    return jsonify({"status": "healthy", "message": "Nearest Station API is running"})

@app.route("/", methods=["GET"])
def home():
    """Home endpoint with usage instructions"""
    return jsonify({
        "message": "Nearest Station API",
        "usage": "GET /nearest_station?lat=LATITUDE&lng=LONGITUDE",
        "example": "GET /nearest_station?lat=19.086832&lng=72.905479",
        "parameters": {
            "lat": "Latitude (required, decimal degrees)",
            "lng": "Longitude (required, decimal degrees)"
        },
        "health_check": "GET /health"
    })

if __name__ == "__main__":
    # print("🚀 Starting Nearest Station API...")
    # print("📍 API will be available at: http://127.0.0.1:5000")
    # print("🏥 Health check: http://127.0.0.1:5000/health")
    # print("🔍 Test endpoint: http://127.0.0.1:5000/nearest_station?lat=19.086832&lng=72.905479")
    app.run(debug=True, host='0.0.0.0', port=5000)