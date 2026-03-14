package grpcclient

import (
	"sync"
	"time"

	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

type CircuitBreaker struct {
	mu               sync.Mutex
	state            string
	failureCount     int
	openUntil        time.Time
	halfOpenInFlight bool
	cfg              CBConfig
}

func NewCircuitBreaker(cfg CBConfig) *CircuitBreaker {
	if cfg.FailureThreshold <= 0 {
		cfg.FailureThreshold = 5
	}
	if cfg.OpenTimeout <= 0 {
		cfg.OpenTimeout = 20 * time.Second
	}
	return &CircuitBreaker{state: "closed", cfg: cfg}
}

func (c *CircuitBreaker) Allow() bool {
	c.mu.Lock()
	defer c.mu.Unlock()

	now := time.Now()
	switch c.state {
	case "open":
		if now.After(c.openUntil) {
			c.transition("half_open")
			c.halfOpenInFlight = false
		} else {
			return false
		}
		fallthrough
	case "half_open":
		if c.halfOpenInFlight {
			return false
		}
		c.halfOpenInFlight = true
		return true
	default:
		return true
	}
}

func (c *CircuitBreaker) OnSuccess() {
	c.mu.Lock()
	defer c.mu.Unlock()

	if c.state == "half_open" {
		c.transition("closed")
		c.failureCount = 0
		c.halfOpenInFlight = false
		return
	}
	c.failureCount = 0
}

func (c *CircuitBreaker) OnFailure(err error) {
	if !isBreakerError(err) {
		return
	}

	c.mu.Lock()
	defer c.mu.Unlock()

	switch c.state {
	case "half_open":
		c.openUntil = time.Now().Add(c.cfg.OpenTimeout)
		c.transition("open")
		c.halfOpenInFlight = false
	case "closed":
		c.failureCount++
		if c.failureCount >= c.cfg.FailureThreshold {
			c.openUntil = time.Now().Add(c.cfg.OpenTimeout)
			c.transition("open")
		}
	}
}

func (c *CircuitBreaker) transition(state string) {
	from := c.state
	c.state = state
	logStateChange(from, state)
}

func isBreakerError(err error) bool {
	st, ok := status.FromError(err)
	if !ok {
		return false
	}
	return st.Code() == codes.Unavailable || st.Code() == codes.DeadlineExceeded
}
