FROM python:3.10-slim

WORKDIR /app

# System dependencies for OpenCV, PaddlePaddle, and building opencv-contrib-python
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    git \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

# Install CPU-only PyTorch first to avoid pulling GPU packages
RUN pip install --no-cache-dir torch==2.3.0 torchvision==0.18.0 --index-url https://download.pytorch.org/whl/cpu

# Install Python dependencies — first upgrade pip and packaging to avoid resolver bugs
COPY requirements.txt .
RUN pip install --upgrade pip packaging \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8001

CMD ["python", "-m", "uvicorn", "fax_ingress.app:app", "--host", "0.0.0.0", "--port", "8001"]