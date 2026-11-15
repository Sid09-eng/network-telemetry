FROM python:3.12-alpine3.21

WORKDIR /app
COPY app.py /app/app.py

USER 65532:65532
EXPOSE 8001
ENTRYPOINT ["python", "/app/app.py"]
