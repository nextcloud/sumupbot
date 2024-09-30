FROM python:3.11-alpine

COPY requirements.txt /
RUN \
  python3 -m pip install -r requirements.txt && rm -rf ~/.cache && rm requirements.txt

ADD li[b] /app/lib

WORKDIR /app/lib
ENTRYPOINT ["python3", "-u", "main.py"]

LABEL org.opencontainers.image.source=https://github.com/nextcloud/summary_bot
