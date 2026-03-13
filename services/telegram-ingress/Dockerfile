FROM python:3.12-slim
WORKDIR /app
COPY services/telegram-ingress/requirements.txt /app/requirements.txt
COPY shared_infra /app/shared_infra
RUN pip install --no-cache-dir --upgrade pip setuptools \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir --no-build-isolation /app/shared_infra
COPY services/telegram-ingress/app /app/app
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
