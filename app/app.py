import os
import requests
import pandas as pd
import psycopg2
from datetime import datetime, timedelta, timezone
import dash
from dash import dcc, html
import plotly.express as px
import sys

# --- Configuration ---
DB_USER = os.getenv('DB_USER', 'user')
DB_PASSWORD = os.getenv('DB_PASSWORD', 'password')
DB_HOST = os.getenv('DB_HOST', 'db')
DB_PORT = os.getenv('DB_PORT', '5432')
DB_NAME = os.getenv('DB_NAME', 'env_monitoring')
DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
SENSEBOX_ID = os.getenv('SENSEBOX_ID')

# see https://docs.opensensemap.org/#api-Measurements-getData
METADATA_API_URL = f"https://api.opensensemap.org/boxes/{SENSEBOX_ID}?format=json"
SENSOR_DATA_API_URL_FORMAT = "https://api.opensensemap.org/boxes/{sensebox_id}/data/{sensor_id}"

print("--- Starting Initial Data Load ---")
conn_insert = None
try:
    conn_insert = psycopg2.connect(DATABASE_URL)
    cursor_insert = conn_insert.cursor()

    # 1. Fetch Metadata
    print(f"Fetching metadata for SenseBox ID: {SENSEBOX_ID}")
    meta_response = requests.get(METADATA_API_URL, timeout=30)
    meta_response.raise_for_status() # Exit on bad status (4xx, 5xx)
    metadata = meta_response.json()

    if not metadata or 'sensors' not in metadata:
        print("Error: Could not retrieve valid metadata or no sensors found.", file=sys.stderr)
        sys.exit(1)

    # Store sensor metadata (type, unit, icon) by sensor_id
    sensor_details = {
        s['_id']: {
            'type': s.get('sensorType', 'unknown'),
            'unit': s.get('unit', ''),
            'icon': s.get('icon', None) # Allow icon to be None
        }
        for s in metadata['sensors'] if '_id' in s
    }

    # 2. Fetch and Insert Data for Each Sensor
    for sensor_id, details in sensor_details.items():
        print(f"Fetching data for Sensor ID: {sensor_id} (Type: {details['type']})")
        data_url = SENSOR_DATA_API_URL_FORMAT.format(
            sensebox_id=SENSEBOX_ID,
            sensor_id=sensor_id,
        )

        try:
            data_response = requests.get(data_url, timeout=60)
            data_response.raise_for_status()
            sensor_data = data_response.json()

            if sensor_data: # Check if list is not empty
                # Prepare data for insertion
                data_to_insert = []
                for item in sensor_data:
                    # Basic check for essential fields
                    if 'createdAt' in item and 'value' in item:
                        try:
                            # Ensure measurement is float, handle potential None or errors
                            measurement_val = float(item['value']) if item['value'] is not None else None
                            data_to_insert.append((
                                item['createdAt'],         # timestamp (TIMESTAMPTZ)
                                SENSEBOX_ID,               # box_id (TEXT)
                                sensor_id,                 # sensor_id (TEXT)
                                measurement_val,           # measurement (DOUBLE PRECISION)
                                details['unit'],           # unit (TEXT)
                                details['type'],           # sensor_type (TEXT)
                                details['icon']            # icon (TEXT)
                            ))
                        except (ValueError, TypeError):
                             print(f"Warning: Could not convert value '{item['value']}' to float for sensor {sensor_id} at {item['createdAt']}. Skipping point.", file=sys.stderr)

                if data_to_insert:
                    # Insert data, ignoring conflicts (based on UNIQUE constraint in init.sql)
                    insert_query = """
                        INSERT INTO sensor_data (timestamp, box_id, sensor_id, measurement, unit, sensor_type, icon)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (timestamp, box_id, sensor_id) DO NOTHING;
                    """
                    cursor_insert.executemany(insert_query, data_to_insert)
                    conn_insert.commit() # Commit after each sensor's data is processed
                    print(f"Inserted {len(data_to_insert)} records for sensor {sensor_id}.")
                else:
                    print(f"No valid data points found to insert for sensor {sensor_id}.")
            else:
                 print(f"No data returned from API for sensor {sensor_id}.")

        except requests.exceptions.RequestException as e:
            print(f"Warning: Failed to fetch or process data for sensor {sensor_id}: {e}", file=sys.stderr)
        except Exception as e_inner:
             print(f"Warning: An unexpected error occurred processing sensor {sensor_id}: {e_inner}", file=sys.stderr)

    print("--- Initial Data Load Complete ---")

except requests.exceptions.RequestException as e:
    print(f"Error during initial data load (API request failed): {e}", file=sys.stderr)
    sys.exit(1)
except psycopg2.Error as db_err:
    print(f"Error during initial data load (Database error): {db_err}", file=sys.stderr)
    sys.exit(1)
except Exception as e:
    print(f"An unexpected error occurred during initial data load: {e}", file=sys.stderr)
    sys.exit(1)
finally:
    if conn_insert:
        cursor_insert.close()
        conn_insert.close()
        print("Database connection (insert) closed.")


# --- Prepare Data for Dashboard ---
conn_read = None
df_all_sensors = pd.DataFrame() # Initialize empty DataFrame
try:
    conn_read = psycopg2.connect(DATABASE_URL)
    print(f"Fetching data from database for dashboard (Box ID: {SENSEBOX_ID})")
    # Fetch relevant columns needed for plotting
    query = """
        SELECT timestamp, measurement, sensor_id, sensor_type, unit
        FROM sensor_data
        WHERE box_id = %s
        ORDER BY sensor_type, sensor_id, timestamp;
        """
    df_all_sensors = pd.read_sql_query(query, conn_read, params=(SENSEBOX_ID,))
    print(f"Fetched {len(df_all_sensors)} records from database for dashboard.")

except psycopg2.Error as db_err:
    print(f"Error fetching data for dashboard: {db_err}", file=sys.stderr)
    # Keep df_all_sensors as empty
except Exception as e:
    print(f"Error fetching data for dashboard: {e}", file=sys.stderr)
     # Keep df_all_sensors as empty
finally:
    if conn_read:
        conn_read.close()
        print("Database connection (read) closed.")

# --- Create Dash App and Layout ---
app = dash.Dash(__name__)
app.title = f"SenseBox Dashboard: {SENSEBOX_ID}"

graphs = []
if not df_all_sensors.empty:
    # Ensure 'measurement' is numeric, converting errors to NaN
    df_all_sensors['measurement'] = pd.to_numeric(df_all_sensors['measurement'], errors='coerce')
    # Remove rows where conversion failed (measurement is NaN) or timestamp is invalid
    df_all_sensors.dropna(subset=['measurement', 'timestamp'], inplace=True)
    # Convert timestamp column to datetime objects for Plotly
    df_all_sensors['timestamp'] = pd.to_datetime(df_all_sensors['timestamp'])


    # Generate a graph for each unique sensor_id
    unique_sensor_ids = df_all_sensors['sensor_id'].unique()
    print(f"Generating graphs for sensors: {unique_sensor_ids}")

    for sensor_id in unique_sensor_ids:
        df_sensor = df_all_sensors[df_all_sensors['sensor_id'] == sensor_id]
        if not df_sensor.empty:
            # Get sensor type and unit from the first row (should be same for all rows of this sensor_id)
            sensor_type = df_sensor['sensor_type'].iloc[0]
            unit = df_sensor['unit'].iloc[0]
            graph_title = f"Type: {sensor_type} (ID: {sensor_id})"
            yaxis_title = f"{sensor_type} ({unit})" if unit else sensor_type

            fig = px.line(
                df_sensor,
                x='timestamp',
                y='measurement',
                title=graph_title,
                labels={'timestamp': 'Time', 'measurement': yaxis_title}
            )
            fig.update_layout(margin=dict(l=20, r=20, t=40, b=20))
            graphs.append(dcc.Graph(figure=fig))
        else:
            print(f"No plottable data found for sensor {sensor_id} after cleaning.")
else:
     print("No data retrieved from database or data is empty after cleaning. No graphs will be displayed.")

# --- App Layout ---
app.layout = html.Div(children=[
    html.H1(children=f'SenseBox Data Dashboard (ID: {SENSEBOX_ID})'),
    html.Hr(),
    # Display graphs if any were generated, otherwise show a message
    html.Div(children=graphs if graphs else html.P("No data available to display graphs."))
])

# --- Run the App ---
if __name__ == '__main__':
    # Use host='0.0.0.0' to make it accessible outside the container
    app.run(debug=True, host='0.0.0.0', port=8050)