#!/usr/bin/env sh
set -e

protoc \
	-I . \
	-I /usr/local/include \
	-I /usr/include \
	--go_out=. \
	--go-grpc_out=. \
	--go_opt=paths=source_relative \
	--go-grpc_opt=paths=source_relative \
	flight_service/proto/flight_service.proto
