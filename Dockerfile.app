FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV STREAMLIT_SERVER_PORT=10000
CMD ["streamlit", "run", "app.py", "--server.headless", "true", "--server.port", "10000", "--browser.gatherUsageStats", "false"]
