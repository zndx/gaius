# Start from a base image for elixir
# Phoenix works best on pre 1.7 at the moment.
FROM elixir:1.10.4-alpine

# Set up Elixir and Phoenix
ARG APP_NAME=${APP_NAME}
ARG PHOENIX_SUBDIR=.
ENV SECRET_KEY_BASE=${SECRET_KEY_BASE}
ENV MIX_ENV=prod REPLACE_OS_VARS=true TERM=xterm
WORKDIR /opt/app

# Update nodejs, rebar, and hex.
RUN apk update \
    && apk --no-cache --update add tree nodejs nodejs-npm \
    && mix local.rebar --force \
    && mix local.hex --force
COPY . .

# Download and compile dependencies, then compile Web app.
RUN mix do deps.get, deps.compile, compile
RUN cd ${PHOENIX_SUBDIR}/assets \
    && npm install \
    && ./node_modules/brunch/bin/brunch build -p \
    && cd .. \
    && mix phx.digest

# Create a release version of the application
RUN mix release \
    && mv _build/prod/rel/${APP_NAME} /opt/release \
    && tree /opt
#    && mv /opt/release/gaius/bin/gaius /opt/release/bin/start_server

# Prepare final layer
FROM alpine:latest
RUN apk update && apk --no-cache --update add bash openssl-dev ca-certificates

# Add a user so the server will run as a non-root user.
RUN addgroup -g 1000 appuser && \
    adduser -S -u 1000 -G appuser appuser
# Pre-create necessary temp directory for erlang and set permissions.
RUN mkdir -p /opt/app/var
RUN chown appuser /opt/app/var
# Run everything else as 'appuser'
USER appuser

ENV MIX_ENV=prod REPLACE_OS_VARS=true
WORKDIR /opt/app
COPY --from=0 /opt/release .
ENV RUNNER_LOG_DIR /var/log

# Command to execute the application.
CMD ["/opt/release/gaius/bin/gaius", "start", "boot_var=/tmp"]

