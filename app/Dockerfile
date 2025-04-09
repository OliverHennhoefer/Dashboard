# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container at /app
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
# --no-cache-dir reduces image size
# --trusted-host pypi.python.org avoids SSL issues in some environments
RUN pip install --no-cache-dir --trusted-host pypi.python.org -r requirements.txt

# Copy the current directory contents into the container at /app
COPY . .

# Make port 8050 available to the world outside this container
EXPOSE 8050

# Define environment variable (optional, can also be set in docker-compose)
# ENV NAME World

# Run app.py when the container launches
# Use gunicorn for production later, but python for simplicity now
CMD ["python", "app.py"]