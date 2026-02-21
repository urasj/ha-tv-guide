FROM python:3.11-alpine

ENV LANG=C.UTF-8

RUN apk add --no-cache jq bash

WORKDIR /app

COPY app/requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY app/ .

COPY run.sh /run.sh
RUN chmod +x /run.sh

CMD ["/run.sh"]
