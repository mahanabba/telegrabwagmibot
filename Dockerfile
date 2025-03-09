# Use an official Python runtime as a base image.
FROM python:3.9-slim

# Set the working directory inside the container.
WORKDIR /app

# Copy dependency list and install dependencies.
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy the rest of your app’s code.
COPY . .

# Expose the port your app will run on (e.g., 8080)
EXPOSE 8080

# Define the command to run your app.
CMD ["python", "app.py"]
