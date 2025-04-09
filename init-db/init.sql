-- Ensure the timescaledb extension is available
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- Create the sensor data table
CREATE TABLE IF NOT EXISTS sensor_data (
    timestamp   TIMESTAMPTZ       NOT NULL,
    box_id      TEXT              NOT NULL,
    sensor_id   TEXT              NOT NULL,
    measurement DOUBLE PRECISION, -- Use DOUBLE PRECISION for floating point values
    unit        TEXT,
    sensor_type TEXT,
    icon        TEXT,
    -- Define composite primary key or unique constraint for ON CONFLICT
    UNIQUE (timestamp, box_id, sensor_id)
);

-- Create the TimescaleDB hypertable, partitioning by time
-- if_not_exists prevents error if script is run multiple times
SELECT create_hypertable('sensor_data', 'timestamp', if_not_exists => TRUE);

-- Optional: Add indexes for faster queries
CREATE INDEX IF NOT EXISTS idx_sensor_data_box_id_ts ON sensor_data (box_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_sensor_data_sensor_id_ts ON sensor_data (sensor_id, timestamp DESC);