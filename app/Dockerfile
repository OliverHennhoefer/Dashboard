# Basis is a Python 3.12 docker image
FROM python:3.12-slim

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container at /app (working directory)
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
# add --no-cache-dir to reduce image size
# add --trusted-host pypi.python.org to avoid SSL issues in some environments
RUN pip install -r requirements.txt

# Copy the program logic (.py) into the container at /app level
COPY app.py .

# Make port 8050 available to the world outside this container
EXPOSE 8050

# Define environment variable (optional, can also be set in docker-compose)
# ENV NAME World

# Run app.py when the container launches
# Use gunicorn for production later, but python for simplicity now
# This is how you would also run the script locally on your machine
CMD ["python", "app.py"]