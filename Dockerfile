# Stage 1: Builder
# We use a full python image to install dependencies
FROM python:3.11-slim as builder

WORKDIR /app

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Install build dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc python3-dev

# Install dependencies into a virtual env
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: Final Runtime
# We use a fresh slim image and only copy the necessary files
FROM python:3.11-slim

WORKDIR /app

# Copy the virtual env from the builder stage
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy your application code
COPY . .

# Create a non-privileged user for security (Low-cost hosts love this)
RUN adduser --disabled-password --gecos "" copituser
USER copituser

# Expose the port FastAPI runs on
EXPOSE 8000

# Run the app using uvicorn
# --proxy-headers is critical for working with Vercel/Cloudflare/Railway proxies
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]