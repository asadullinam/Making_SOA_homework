FROM golang:1.22-alpine AS build

RUN apk add --no-cache git protobuf protobuf-dev

ENV PATH="/go/bin:$PATH"
RUN go install google.golang.org/protobuf/cmd/protoc-gen-go@v1.33.0
RUN go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@v1.3.0

WORKDIR /app
COPY go.mod go.sum ./
RUN for i in 1 2 3 4 5; do go mod download && exit 0; sleep $((i * 2)); done; exit 1

COPY . .

RUN sh ./scripts/gen_proto.sh
RUN CGO_ENABLED=0 go build -o /bin/flight ./flight_service/cmd/flight

FROM alpine:3.19
WORKDIR /app

COPY --from=build /bin/flight /app/flight
COPY flight_service/migrations /app/flight_service/migrations
COPY flight_service/proto /app/flight_service/proto

ENV GRPC_ADDR=:50051

CMD ["/app/flight"]
