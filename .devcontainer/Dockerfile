FROM python:3.10

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    wget \
    nodejs \
    npm \
    libpq-dev \
    libxml2-dev \
    libxslt-dev \
    libldap2-dev \
    libsasl2-dev \
    libffi-dev \
    libssl-dev \
    python3-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Set workdir
WORKDIR /workspace

# Copy requirements (optional)
COPY requirements.txt .

RUN pip install -r requirements.txt || true
