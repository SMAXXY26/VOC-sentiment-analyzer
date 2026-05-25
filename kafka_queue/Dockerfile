FROM rust:1.86-bookworm AS builder

RUN apt-get update && apt-get install -y \
    cmake libssl-dev pkg-config libsasl2-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY Cargo.toml Cargo.lock* ./
COPY src ./src

RUN cargo build --release --bin producer --bin consumer

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y libssl3 libsasl2-2 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/target/release/producer /usr/local/bin/producer
COPY --from=builder /app/target/release/consumer /usr/local/bin/consumer
