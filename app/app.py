import os
import requests
import json
import pandas
import logging
import time
from datetime import datetime, timedelta # Added timedelta

from sqlalchemy import create_engine, text, exc
import psycopg2 # Import needed for sqlalchemy to recognize postgresql dialect, even if not directly used

import dash
from dash import dcc, html, Input, Output, State, callback # Added callback decorator explicitly
import plotly.graph_objects as go # Import plotly

# --- Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Database connection - get details from environment variables
DB_USER = os.getenv('DB_USER', 'user')
DB_PASSWORD = os.getenv('DB_PASSWORD', 'password')
DB_HOST = os.getenv('DB_HOST', 'db')
DB_PORT = os.getenv('DB_PORT', '5432')
DB_NAME = os.getenv('DB_NAME', 'env_monitoring')
DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# API Configuration
SENSEBOX_ID = os.getenv('SENSEBOX_ID', '6252afcfd7e732001bb6b9f7')  # Second value is the fall-back
API_URL_FORMAT = os.getenv('API_URL_FORMAT', 'https://api.opensensemap.org/boxes/{sensebox_id}?format={response_format}')
RESPONSE_FORMAT = "json"

# Graph Configuration
GRAPH_TIME_WINDOW_HOURS = 24 # How many hours of data to show on graphs
MAX_GRAPH_POINTS = 500 # Limit points per graph for performance

# --- Database Setup ---
engine = None
MAX_RETRIES = 5
RETRY_DELAY = 5 # seconds

for attempt in range(MAX_RETRIES):
    try:
        engine = create_engine(DATABASE_URL)
        # Test connection
        with engine.connect() as connection:
            logging.info("Database connection successful!")
        break # Exit loop if connection successful
    except (exc.OperationalError, psycopg2.OperationalError) as e:
        logging.warning(f"Database connection attempt {attempt + 1}/{MAX_RETRIES} failed: {e}")
        if attempt + 1 == MAX_RETRIES:
            logging.error("Could not connect to the database after several retries. Dashboard might not function correctly.")
            engine = None # Ensure engine is None if connection failed
        time.sleep(RETRY_DELAY)

# --- Helper Functions ---

def fetch_sensor_data(box_id):
    """Fetches sensor data from the OpenSenseMap API."""
    url = API_URL_FORMAT.format(sensebox_id=box_id, response_format=RESPONSE_FORMAT)
    logging.info(f"Fetching data from: {url}")
    try:
        result = requests.get(url, timeout=15) # Increased timeout slightly
        result.raise_for_status()
        content = result.json()
        sensors = content.get("sensors")
        if not sensors:
            logging.warning(f"No sensors found in the response for box_id {box_id}")
            return None

        df = pandas.json_normalize(sensors)

        if 'lastMeasurement.createdAt' not in df.columns:
            logging.warning(f"Field 'lastMeasurement.createdAt' not found for all sensors in box_id {box_id}.")
            return None # Can't proceed without timestamps

        # Filter out rows where timestamp or value might be missing *before* processing
        df = df.dropna(subset=['lastMeasurement.createdAt', 'lastMeasurement.value'])
        if df.empty:
            logging.warning(f"No valid sensor readings with timestamp and value found for {box_id}.")
            return None

        df_filtered = df.copy()
        df_filtered['timestamp'] = pandas.to_datetime(df_filtered['lastMeasurement.createdAt'])
        # Measurement conversion handled later during DB write preparation if needed

        required_cols = {
            'timestamp': 'timestamp',
            '_id': 'sensor_id',
            'lastMeasurement.value': 'measurement',
            'unit': 'unit',
            'sensorType': 'sensor_type',
            'icon': 'icon'
        }
        cols_to_select = {k: v for k, v in required_cols.items() if k in df_filtered.columns}
        df_final = df_filtered[list(cols_to_select.keys())].rename(columns=cols_to_select)

        # Attempt numeric conversion, keep track of failures
        original_len = len(df_final)
        df_final['measurement'] = pandas.to_numeric(df_final['measurement'], errors='coerce')
        df_final = df_final.dropna(subset=['measurement']) # Remove rows where conversion failed
        if len(df_final) < original_len:
             logging.warning(f"Removed {original_len - len(df_final)} rows due to non-numeric 'measurement' values.")

        logging.info(f"Successfully fetched and processed {len(df_final)} sensor readings.")
        return df_final

    except requests.exceptions.RequestException as e:
        logging.error(f"API request failed: {e}")
        return None
    except (json.JSONDecodeError, KeyError, TypeError) as e: # Added TypeError
        logging.error(f"Failed to parse or process API response: {e}")
        return None


def write_sensor_data(db_engine, box_id, df):
    """Write sensor data DataFrame to database, avoiding duplicates."""
    if df is None or df.empty:
        logging.warning("No data provided to write.")
        return 0
    if db_engine is None:
        logging.error("Database engine not available. Cannot write data.")
        return 0

    inserted_count = 0
    with db_engine.begin() as conn: # Use transaction
        for _, row in df.iterrows():
            # Check for NaN/None which shouldn't happen due to earlier dropna, but safety check
            measurement_value = row.get('measurement')
            if pandas.isna(measurement_value):
                logging.warning(f"Skipping row due to NaN measurement: {row.to_dict()}")
                continue # Skip this row

            # Ensure timestamp is valid
            timestamp_value = row.get('timestamp')
            if pandas.isna(timestamp_value):
                 logging.warning(f"Skipping row due to invalid timestamp: {row.to_dict()}")
                 continue # Skip this row

            try:
                # Using ON CONFLICT requires timestamp to be precise enough to avoid collisions
                # Ensure the timestamp has sufficient resolution if needed
                conn.execute(text("""
                    INSERT INTO sensor_data (
                        timestamp, box_id, sensor_id, measurement,
                        unit, sensor_type, icon
                    ) VALUES (
                        :timestamp, :box_id, :sensor_id, :value,
                        :unit, :sensor_type, :icon
                    )
                    ON CONFLICT (timestamp, box_id, sensor_id) DO NOTHING;
                """), {
                    'timestamp': timestamp_value,
                    'box_id': box_id,
                    'sensor_id': row.get('sensor_id'), # sensor_id might be None/NaN from API, DB should allow NULL
                    'value': float(measurement_value), # Already confirmed not NaN
                    'unit': row.get('unit'),
                    'sensor_type': row.get('sensor_type'),
                    'icon': row.get('icon')
                })
                # Note: Can't reliably count inserted rows with ON CONFLICT easily across DBs
                inserted_count += 1 # Counts attempts, not necessarily successful insertions
            except Exception as e:
                logging.error(f"Error inserting row: {row.to_dict()} - Error: {e}")

    logging.info(f"Attempted to process {inserted_count} rows for box_id {box_id}. Duplicates were ignored via ON CONFLICT.")
    return inserted_count # Return number of rows processed

def query_graph_data(db_engine, box_id, time_window_hours, max_points):
    """Queries recent sensor data from the database for graphing."""
    if db_engine is None:
        logging.error("Database engine not available for querying graph data.")
        return None

    logging.info(f"Querying graph data for box {box_id}, last {time_window_hours} hours.")
    try:
        cutoff_time = datetime.utcnow() - timedelta(hours=time_window_hours)
        # Assuming timestamp column is TIMESTAMPTZ or TIMESTAMP WITHOUT TIME ZONE storing UTC
        # Adjust timezone handling if necessary based on your DB schema ('UTC' below assumes psycopg2 handles it)
        query = text("""
            SELECT timestamp, box_id, sensor_id, sensor_type, measurement, unit
            FROM sensor_data
            WHERE box_id = :box_id
              AND timestamp >= :cutoff
            ORDER BY timestamp ASC -- Order by time for plotting
        """)
        # Further optimization: Limit points per sensor in SQL if possible,
        # but simpler to fetch and then maybe downsample in pandas if needed.
        # The MAX_GRAPH_POINTS limit is applied later during graph generation for simplicity here.

        with db_engine.connect() as conn:
            df = pandas.read_sql(query, conn, params={'box_id': box_id, 'cutoff': cutoff_time},
                                 parse_dates=['timestamp']) # Auto-parse timestamp column

        logging.info(f"Retrieved {len(df)} data points for graphs.")
        return df

    except Exception as e:
        logging.error(f"Error querying graph data: {e}")
        return None

# --- Dash Application ---
app = dash.Dash(__name__, suppress_callback_exceptions=True) # Suppress required if targets of callbacks are created by other callbacks
app.title = "Sensor Data Dashboard"

app.layout = html.Div(children=[
    html.H1(children=f'OpenSenseMap Sensor Data (Box: {SENSEBOX_ID})'),

    html.Button('Fetch Latest Data & Update Graphs', id='fetch-button', n_clicks=0),
    html.Div(id='output-status', children='Dashboard loaded. Click button to fetch initial data.'),

    # Interval component for automatic refresh (optional)
    # dcc.Interval(
    #     id='interval-component',
    #     interval=5*60*1000, # in milliseconds (e.g., 5 minutes)
    #     n_intervals=0
    # ),

    # Store for holding graph data (JSON format)
    dcc.Store(id='graph-data-store'),

    # Container where graphs will be dynamically added
    html.Div(id='graph-container', children=[
         html.P("Graphs will appear here after fetching data.")
    ]),

    html.Hr(),
    html.Footer("Dashboard End")
])

# --- Callbacks ---

# Callback 1: Fetch API data, write to DB, and update status message
@callback(
    Output('output-status', 'children'),
    Input('fetch-button', 'n_clicks'),
    prevent_initial_call=True # Don't run on page load automatically via button
)
def update_db_and_status(n_clicks):
    if n_clicks > 0:
        logging.info(f"Fetch button clicked ({n_clicks} times). Fetching data from API...")
        df_api = fetch_sensor_data(SENSEBOX_ID)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if df_api is not None and not df_api.empty:
            write_count = write_sensor_data(engine, SENSEBOX_ID, df_api)
            # Return status AFTER write attempt
            return f"[{timestamp}] API Fetch successful. Processed {len(df_api)} readings. Attempted to write {write_count} to DB. Graphs will update shortly."
        elif df_api is not None and df_api.empty:
            return f"[{timestamp}] API Fetch successful, but no processable data found."
        else:
            return f"[{timestamp}] Failed to fetch or process data from API. Check logs."

    return dash.no_update # Should not happen with prevent_initial_call=True

# Callback 2: Query DB for graph data and store it
@callback(
    Output('graph-data-store', 'data'),
    Input('fetch-button', 'n_clicks'),
    # Input('interval-component', 'n_intervals') # Add this if using interval
    prevent_initial_call=False # Run once on load, and when button is clicked
)
def update_graph_store(n_clicks): # , n_intervals): # Add n_intervals if using interval
    # Determine what triggered the callback (useful if using multiple inputs)
    ctx = dash.callback_context
    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0] if ctx.triggered else 'initial load'
    logging.info(f"Graph store update triggered by: {trigger_id}")

    # Query data regardless of trigger (initial load or button press)
    df_db = query_graph_data(engine, SENSEBOX_ID, GRAPH_TIME_WINDOW_HOURS, MAX_GRAPH_POINTS)

    if df_db is None or df_db.empty:
        logging.warning("No data retrieved from DB for graphs.")
        return {} # Return empty dict for store if no data

    # --- Prepare data for JSON storage ---
    # Group by sensor (prefer sensor_id, fallback to sensor_type)
    graph_data = {}

    # Create a combined identifier, handling potential None sensor_id
    df_db['sensor_key'] = df_db.apply(
        lambda row: f"{row['box_id']}_{row['sensor_id']}" if pandas.notna(row['sensor_id']) else f"{row['box_id']}_{row['sensor_type']}",
        axis=1
    )
    # Add unit to the key for clarity if needed, e.g., if same sensor reports multiple units (unlikely here)
    # df_db['sensor_key'] = df_db.apply(
    #    lambda row: f"{row['box_id']}_{row['sensor_id'] or row['sensor_type']}_{row['unit']}", axis=1
    # )

    grouped = df_db.groupby('sensor_key')

    for name, group in grouped:
        # Sort by timestamp just in case DB didn't guarantee it within group
        group = group.sort_values('timestamp')
        # Limit points per graph here if not done in SQL
        if len(group) > MAX_GRAPH_POINTS:
            group = group.tail(MAX_GRAPH_POINTS)

        graph_data[name] = {
            'timestamps': group['timestamp'].dt.strftime('%Y-%m-%dT%H:%M:%S').tolist(), # ISO format string for JSON
            'values': group['measurement'].tolist(),
            'unit': group['unit'].iloc[0] if not group['unit'].empty else '' # Get unit from first row
        }

    logging.info(f"Prepared data for {len(graph_data)} graphs.")
    return graph_data # Store as JSON serializable dictionary


# Callback 3: Generate graphs from stored data
@callback(
    Output('graph-container', 'children'),
    Input('graph-data-store', 'data')
)
def update_graphs(stored_data):
    if not stored_data:
        # Keep the initial message or provide a dynamic one
        # Use the P element from the initial layout or create a new one
        if engine is None:
             return html.P("Graphs cannot be displayed: Database connection failed.")
        else:
             return html.P("No data available to display graphs. Click 'Fetch' or wait for data.")


    logging.info(f"Updating graphs from stored data ({len(stored_data)} series).")
    graph_components = []
    sorted_keys = sorted(stored_data.keys()) # Sort alphabetically for consistent order

    for sensor_key in sorted_keys:
        sensor_data = stored_data[sensor_key]
        timestamps = sensor_data.get('timestamps', [])
        values = sensor_data.get('values', [])
        unit = sensor_data.get('unit', '')
        title = f"{sensor_key} ({unit})"

        if not timestamps or not values:
            logging.warning(f"Skipping graph for {sensor_key} due to missing data.")
            continue

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=pandas.to_datetime(timestamps), # Convert back to datetime for plotly
            y=values,
            mode='lines+markers',
            name=sensor_key
        ))

        fig.update_layout(
            title=title,
            xaxis_title='Timestamp',
            yaxis_title=f'Measurement ({unit})',
            margin=dict(l=40, r=20, t=40, b=30), # Adjust margins
            height=300 # Set a fixed height for each graph
        )

        graph_components.append(
            html.Div(className="graph-item", children=[ # Optional wrapper div
                 dcc.Graph(figure=fig, id={'type': 'dynamic-graph', 'index': sensor_key}) # Using pattern-matching ID is optional here
            ])
        )

    logging.info(f"Generated {len(graph_components)} graph components.")
    return graph_components


# --- Run Application ---
if __name__ == '__main__':
    # NOTE: Initial data load for graphs happens via the update_graph_store callback
    # triggered by prevent_initial_call=False on app startup.
    if engine is None:
        logging.warning("Starting Dash app without a database connection. Graphing will not work.")
        # You might choose to exit here if DB is critical
        # exit(1)

    app.run(debug=True, host='0.0.0.0', port=8050)