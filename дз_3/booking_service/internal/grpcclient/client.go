package grpcclient

import (
	"context"
	"log"
	"time"

	flightv1 "github.com/aydar/soa-dz3/flight_service/proto"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
)

type Client struct {
	conn   *grpc.ClientConn
	client flightv1.FlightServiceClient
	apiKey string
	cb     *CircuitBreaker
}

type CBConfig struct {
	FailureThreshold int
	OpenTimeout      time.Duration
}

func New(addr, apiKey string, cbCfg CBConfig) (*Client, error) {
	conn, err := grpc.Dial(addr, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		return nil, err
	}
	cb := NewCircuitBreaker(cbCfg)
	return &Client{conn: conn, client: flightv1.NewFlightServiceClient(conn), apiKey: apiKey, cb: cb}, nil
}

func (c *Client) Close() error {
	return c.conn.Close()
}

func (c *Client) SearchFlights(ctx context.Context, req *flightv1.SearchFlightsRequest) (*flightv1.SearchFlightsResponse, error) {
	resp, err := c.callWithRetry(ctx, func(ctx context.Context) (any, error) {
		return c.client.SearchFlights(ctx, req)
	})
	if err != nil {
		return nil, err
	}
	return resp.(*flightv1.SearchFlightsResponse), nil
}

func (c *Client) GetFlight(ctx context.Context, req *flightv1.GetFlightRequest) (*flightv1.GetFlightResponse, error) {
	resp, err := c.callWithRetry(ctx, func(ctx context.Context) (any, error) {
		return c.client.GetFlight(ctx, req)
	})
	if err != nil {
		return nil, err
	}
	return resp.(*flightv1.GetFlightResponse), nil
}

func (c *Client) ReserveSeats(ctx context.Context, req *flightv1.ReserveSeatsRequest) (*flightv1.ReserveSeatsResponse, error) {
	resp, err := c.callWithRetry(ctx, func(ctx context.Context) (any, error) {
		return c.client.ReserveSeats(ctx, req)
	})
	if err != nil {
		return nil, err
	}
	return resp.(*flightv1.ReserveSeatsResponse), nil
}

func (c *Client) ReleaseReservation(ctx context.Context, req *flightv1.ReleaseReservationRequest) (*flightv1.ReleaseReservationResponse, error) {
	resp, err := c.callWithRetry(ctx, func(ctx context.Context) (any, error) {
		return c.client.ReleaseReservation(ctx, req)
	})
	if err != nil {
		return nil, err
	}
	return resp.(*flightv1.ReleaseReservationResponse), nil
}

func (c *Client) withAuth(ctx context.Context) context.Context {
	if c.apiKey == "" {
		return ctx
	}
	md := metadata.Pairs("x-api-key", c.apiKey)
	return metadata.NewOutgoingContext(ctx, md)
}

func (c *Client) callWithRetry(ctx context.Context, fn func(context.Context) (any, error)) (any, error) {
	if c.cb != nil && !c.cb.Allow() {
		return nil, status.Error(codes.Unavailable, "circuit open")
	}

	var lastErr error
	backoff := 100 * time.Millisecond
	for attempt := 0; attempt < 3; attempt++ {
		callCtx, cancel := context.WithTimeout(c.withAuth(ctx), 3*time.Second)
		resp, err := fn(callCtx)
		cancel()
		if err == nil {
			if c.cb != nil {
				c.cb.OnSuccess()
			}
			return resp, nil
		}

		lastErr = err
		if !isRetryable(err) || attempt == 2 {
			break
		}
		time.Sleep(backoff)
		backoff *= 2
	}

	if c.cb != nil {
		c.cb.OnFailure(lastErr)
	}
	return nil, lastErr
}

func isRetryable(err error) bool {
	st, ok := status.FromError(err)
	if !ok {
		return false
	}
	return st.Code() == codes.Unavailable || st.Code() == codes.DeadlineExceeded
}

func logStateChange(from, to string) {
	log.Printf("circuit %s -> %s", from, to)
}
