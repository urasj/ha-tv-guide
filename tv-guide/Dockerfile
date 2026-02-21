ARG BUILD_FROM
FROM $BUILD_FROM

ENV LANG=C.UTF-8

RUN apk add --no-cache python3 py3-pip jq bash

WORKDIR /app

COPY app/requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY app/ .

# s6 service directory
RUN mkdir -p /etc/services.d/tv-guide
COPY services/tv-guide/run /etc/services.d/tv-guide/run
RUN chmod +x /etc/services.d/tv-guide/run
