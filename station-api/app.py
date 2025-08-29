from flask import Flask, request, jsonify
import gspread
from google.oauth2 import service_account
import datetime
import os
import json

app = Flask(__name__)

# Google Sheets setup using env variable instead of file
creds_json = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")
if not creds_json:
    raise Exception("Missing GOOGLE_APPLICATION_CREDENTIALS_JSON in environment variables")

creds_dict = json.loads(creds_json)
creds = service_account.Credentials.from_service_account_info(creds_dict, scopes=[
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
])
client = gspread.authorize(creds)

# Replace with your actual spreadsheet ID
SPREADSHEET_ID = "17cOylW-cc5fKKzHhyknUqwJCOuhwEJkjifVyh8WN5l8"

@app.route("/next_trains", methods=["GET"])
def next_trains():
    source = request.args.get("source")
    destination = request.args.get("destination")
    path = request.args.get("path")   # sheet name e.g. "Ghatkopar-Versova"
    input_time_str = request.args.get("time")  # user-provided time

    if not source or not destination or not path or not input_time_str:
        return jsonify({"error": "Please provide source, destination, path, and time"}), 400

    try:
        spreadsheet = client.open_by_key(SPREADSHEET_ID)
        sheet = spreadsheet.worksheet(path.strip())  # Open specific sheet by name
    except Exception as e:
        return jsonify({"error": f"Could not open sheet: {str(e)}"}), 500

    data = sheet.get_all_values()

    if not data or len(data) < 2:
        return jsonify({"error": "No timetable data found"}), 404

    headers = [h.strip() for h in data[0]]   # first row → station names
    timetable = data[1:]  # rows → train timings

    # Find source/destination columns
    try:
        source_idx = headers.index(source)
        dest_idx = headers.index(destination)
    except ValueError:
        return jsonify({"error": "Invalid source or destination"}), 400

    # Parse user input time
    try:
        clean_time = input_time_str.strip('"').strip("'")   # 🟢 remove quotes if present
        fmt = "%H:%M:%S" if clean_time.count(":") == 2 else "%H:%M"
        now = datetime.datetime.strptime(clean_time, fmt)
        today = datetime.datetime.now()
        now = now.replace(year=today.year, month=today.month, day=today.day)
    except Exception:
        return jsonify({"error": "Invalid time format, use HH:MM or HH:MM:SS"}), 400

    results = []

    for row in timetable:
        if source_idx >= len(row) or dest_idx >= len(row):
            continue

        dep_time_str = row[source_idx].strip()
        arr_time_str = row[dest_idx].strip()

        if not dep_time_str or not arr_time_str:
            continue

        try:
            fmt = "%H:%M:%S" if dep_time_str.count(":") == 2 else "%H:%M"
            dep_time = datetime.datetime.strptime(dep_time_str, fmt)
            dep_time = dep_time.replace(year=now.year, month=now.month, day=now.day)

            if dep_time > now:
                results.append({
                    "departure": dep_time_str,
                    "arrival": arr_time_str
                })
        except Exception:
            continue

    # Take next 3 trains
    next_trains = results[:3]

    output = {
        "train1": next_trains[0] if len(next_trains) > 0 else None,
        "train2": next_trains[1] if len(next_trains) > 1 else None,
        "train3": next_trains[2] if len(next_trains) > 2 else None,
    }

    return jsonify(output)

if __name__ == "__main__":
    app.run(debug=True)
