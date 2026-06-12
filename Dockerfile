FROM python:3.11-slim

# Prevent python from buffering stdout/stderr outputs and writing bytecode
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /code

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Optimize layer caching for Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade -r requirements.txt

# Create non-root system user according to Hugging Face security guidelines
RUN useradd -m -u 1000 user
USER user

# Configure local PATH variable
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

# Copy remaining source code with user-ownership privileges
COPY --chown=user:user . .

# Expose port 7860 as mandated for health probes
EXPOSE 7860

# CMD starting orchestration 
CMD ["python", "bot.py"]
