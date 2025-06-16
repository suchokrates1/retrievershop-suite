FROM debian:bullseye-slim
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    cups-client \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY . /app
RUN pip3 install --no-cache-dir -r requirements.txt
CMD ["python3", "bl_api_print_agent.py"]
