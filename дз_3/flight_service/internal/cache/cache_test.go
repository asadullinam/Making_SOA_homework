package cache

import (
	"context"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	"github.com/redis/go-redis/v9"
)

type sampleFlight struct {
	ID string `json:"id"`
}

func newTestCache(t *testing.T) (*Cache, func()) {
	t.Helper()

	srv, err := miniredis.Run()
	if err != nil {
		t.Fatalf("start miniredis: %v", err)
	}

	client := redis.NewClient(&redis.Options{Addr: srv.Addr()})
	c := &Cache{client: client, ttl: time.Minute}

	cleanup := func() {
		_ = client.Close()
		srv.Close()
	}

	return c, cleanup
}

func TestSetFlightIfNewer(t *testing.T) {
	cache, cleanup := newTestCache(t)
	defer cleanup()

	ctx := context.Background()

	if err := cache.SetFlightIfNewer(ctx, "f1", 2, sampleFlight{ID: "new"}); err != nil {
		t.Fatalf("set newer: %v", err)
	}
	if err := cache.SetFlightIfNewer(ctx, "f1", 1, sampleFlight{ID: "old"}); err != nil {
		t.Fatalf("set older: %v", err)
	}

	var out sampleFlight
	hit, err := cache.GetFlight(ctx, "f1", &out)
	if err != nil {
		t.Fatalf("get flight: %v", err)
	}
	if !hit {
		t.Fatalf("expected cache hit")
	}
	if out.ID != "new" {
		t.Fatalf("expected newest value, got %q", out.ID)
	}
}

func TestSetSearchIfNewer(t *testing.T) {
	cache, cleanup := newTestCache(t)
	defer cleanup()

	ctx := context.Background()

	old := []sampleFlight{{ID: "old"}}
	newer := []sampleFlight{{ID: "new"}}

	if err := cache.SetSearchIfNewer(ctx, "SVO", "LED", "2026-04-01", 3, old); err != nil {
		t.Fatalf("set initial: %v", err)
	}
	if err := cache.SetSearchIfNewer(ctx, "SVO", "LED", "2026-04-01", 4, newer); err != nil {
		t.Fatalf("set newer: %v", err)
	}
	if err := cache.SetSearchIfNewer(ctx, "SVO", "LED", "2026-04-01", 2, old); err != nil {
		t.Fatalf("set older: %v", err)
	}

	var out []sampleFlight
	hit, err := cache.GetSearch(ctx, "SVO", "LED", "2026-04-01", &out)
	if err != nil {
		t.Fatalf("get search: %v", err)
	}
	if !hit {
		t.Fatalf("expected cache hit")
	}
	if len(out) != 1 || out[0].ID != "new" {
		t.Fatalf("expected newest search result")
	}
}

func TestSetVersionIfNewer(t *testing.T) {
	cache, cleanup := newTestCache(t)
	defer cleanup()

	ctx := context.Background()

	if err := cache.SetFlightVersion(ctx, "f2", 10); err != nil {
		t.Fatalf("set version: %v", err)
	}
	if err := cache.SetFlightVersion(ctx, "f2", 9); err != nil {
		t.Fatalf("set older version: %v", err)
	}

	val, err := cache.client.Get(ctx, flightVersionKey("f2")).Result()
	if err != nil {
		t.Fatalf("get version: %v", err)
	}
	if val != "10" {
		t.Fatalf("expected version 10, got %q", val)
	}
}
