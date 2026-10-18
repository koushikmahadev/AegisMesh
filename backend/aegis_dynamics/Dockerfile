# AegisDynamics - Air-Gapped Container Specification
# Multi-stage production container with pre-installed offline dependencies

FROM python:3.11-slim

# Set environment variables for fully offline, non-interactive execution
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

WORKDIR /app

# Install system utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpcap-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency definition and install offline packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code and pre-trained assets
COPY . /app

# Pre-generate mock dataset and pre-train model weights during build to guarantee zero runtime network dependency
RUN python parser.py && python -c "from model import TemporalDynamicsWorldModel, StaticBaselineClassifier, save_models; save_models(TemporalDynamicsWorldModel(), StaticBaselineClassifier())"

# Expose Streamlit default port
EXPOSE 8501

# Health check to ensure air-gapped container responsiveness
HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health || exit 1

# Launch Streamlit server
ENTRYPOINT ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
