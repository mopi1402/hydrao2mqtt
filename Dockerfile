FROM python:3.8.0-alpine

# App base dir
WORKDIR /app

# Copy app
COPY /app .

# Update Alpine and dev tools
RUN apk add --update alpine-sdk glib-dev linux-headers

# Install dependencies
RUN pip3 install -r requirements.txt

# Main command
CMD [ "python", "-u", "main.py" ]