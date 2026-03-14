FROM golang:1.22-alpine AS build

RUN apk add --no-cache git protobuf protobuf-dev

ENV PATH="/go/bin:$PATH"
RUN go install google.golang.org/protobuf/cmd/protoc-gen-go@v1.33.0
RUN go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@v1.3.0

WORKDIR /app
COPY . .

RUN go mod download
RUN sh ./scripts/gen_proto.sh
RUN CGO_ENABLED=0 go build -o /bin/booking ./booking_service/cmd/booking

FROM alpine:3.19
WORKDIR /app

COPY --from=build /bin/booking /app/booking
COPY booking_service/migrations /app/booking_service/migrations
COPY flight_service/proto /app/flight_service/proto

ENV HTTP_ADDR=:8080

CMD ["/app/booking"]
