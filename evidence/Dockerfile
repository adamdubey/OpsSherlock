FROM mcr.microsoft.com/playwright/python:v1.62.0-noble
WORKDIR /app
RUN pip install --no-cache-dir playwright==1.62.0
COPY capture.py /app/capture.py
ENTRYPOINT ["python", "/app/capture.py"]
