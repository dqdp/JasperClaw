FROM python:3.12-slim
WORKDIR /app
COPY platform-db/requirements.txt /app/requirements.txt
COPY shared_infra /app/shared_infra
RUN pip install --no-cache-dir --upgrade pip setuptools \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir --no-build-isolation /app/shared_infra
COPY platform_db /app/platform_db
COPY platform-db /app/platform-db
CMD ["python", "-m", "platform_db.cli", "migrate"]
