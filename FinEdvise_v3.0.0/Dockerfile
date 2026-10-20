# FinEdvise: standard-library Python only, no packages to install.
FROM python:3.12-slim
WORKDIR /app
COPY finedvise ./finedvise
COPY web ./web
COPY data ./data
COPY run.py ./
RUN useradd --create-home finedvise && mkdir -p /app/var && chown finedvise /app/var
USER finedvise
ENV PYTHONUNBUFFERED=1 FINEDVISE_HOST=0.0.0.0 PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,os; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/api/health')"
CMD ["python", "run.py"]
