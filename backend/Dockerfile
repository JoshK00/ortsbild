FROM python:3.12-slim

# Libraries that OpenCV and onnxruntime need at runtime
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# CPU build of torch (the default Linux wheel pulls several GB of CUDA libraries we do not use)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Ship the GLiNER2 model inside the image, the server must not download it at startup
ENV HF_HOME=/opt/hf
RUN python -c "from gliner2 import GLiNER2; GLiNER2.from_pretrained('fastino/gliner2-privacy-filter-PII-multi')"

COPY . .
ENV PYTHONPATH=/app

# Run as a normal user, not as root
RUN useradd --create-home app && mkdir -p /app/logs && chown -R app /app/logs
USER app

EXPOSE 8000
CMD ["uvicorn", "--factory", "api.main:create_app", "--host", "0.0.0.0", "--port", "8000"]
