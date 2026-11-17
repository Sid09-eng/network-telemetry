FROM python:3.12-alpine3.21

WORKDIR /app
COPY forecast /app/forecast

USER 65532:65532
ENTRYPOINT ["python", "-m", "forecast.worker"]
