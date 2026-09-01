FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN python data/synthetic/generator.py

EXPOSE 8501
CMD ["streamlit", "run", "apps/streamlit_app.py", "--server.port=8501", "--server.address=0.0.0.0"]
