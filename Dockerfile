FROM python:3.11-alpine

COPY requirements.txt /

ADD li[b] /app/lib

RUN \
  python3 -m pip install -r requirements.txt && rm -rf ~/.cache && rm requirements.txt

WORKDIR /app/lib
ENTRYPOINT ["python3", "main.py"]

LABEL org.opencontainers.image.source=https://github.com/nextcloud/summary_bot
