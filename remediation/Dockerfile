FROM python:3.14-alpine3.21

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN apk add --no-cache docker-cli=27.3.1-r5 \
    && pip install --no-cache-dir -r /app/requirements.txt
COPY . /app/remediation

# The Docker socket's ownership varies by host; root is needed only when both
# explicit live-action switches are enabled. Dry-run is the default operation.
RUN mkdir -p /data

EXPOSE 8000
ENTRYPOINT ["uvicorn", "remediation.app:app", "--host", "0.0.0.0", "--port", "8000"]
