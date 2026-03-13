FROM python:3.12-slim
WORKDIR /app
COPY services/telegram-ingress/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY services/telegram-ingress/app /app/app
COPY shared_infra /app/shared_infra
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
