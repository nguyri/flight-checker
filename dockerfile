# Use a slim Python image to keep the container footprint small
FROM python:3.12-slim

# Set working directory inside the container
WORKDIR /app

# Install system dependencies (needed for some Python libraries)
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker's caching mechanism
COPY requirements.txt .

# Install dependencies
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy the rest of your application code
COPY . .

# Expose Streamlit's default port
EXPOSE 8501

# Configure Streamlit to handle running smoothly inside a container
HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health

ENTRYPOINT ["streamlit", "run", "main.py", "--server.port=8501", "--server.address=0.0.0.0"]