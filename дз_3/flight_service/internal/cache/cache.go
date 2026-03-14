package cache

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/redis/go-redis/v9"
)

type Cache struct {
	client *redis.Client
	ttl    time.Duration
}

type Config struct {
	Mode      string
	Addr      string
	Sentinels []string
	Master    string
	TTL       time.Duration
}

func New(cfg Config) *Cache {
	var client *redis.Client
	switch cfg.Mode {
	case "sentinel":
		if len(cfg.Sentinels) == 0 {
			return nil
		}
		client = redis.NewFailoverClient(&redis.FailoverOptions{
			MasterName:    cfg.Master,
			SentinelAddrs: cfg.Sentinels,
		})
	default:
		if cfg.Addr == "" {
			return nil
		}
		client = redis.NewClient(&redis.Options{Addr: cfg.Addr})
	}

	return &Cache{client: client, ttl: cfg.TTL}
}

func (c *Cache) Enabled() bool {
	return c != nil && c.client != nil
}

func (c *Cache) GetFlight(ctx context.Context, id string, out any) (bool, error) {
	if !c.Enabled() {
		return false, nil
	}
	key := flightKey(id)
	val, err := c.client.Get(ctx, key).Result()
	if err == redis.Nil {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	return true, json.Unmarshal([]byte(val), out)
}

func (c *Cache) SetFlight(ctx context.Context, id string, v any) error {
	if !c.Enabled() {
		return nil
	}
	key := flightKey(id)
	b, err := json.Marshal(v)
	if err != nil {
		return err
	}
	return c.client.Set(ctx, key, b, c.ttl).Err()
}

func (c *Cache) GetSearch(ctx context.Context, origin, destination, dateKey string, out any) (bool, error) {
	if !c.Enabled() {
		return false, nil
	}
	key := searchKey(origin, destination, dateKey)
	val, err := c.client.Get(ctx, key).Result()
	if err == redis.Nil {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	return true, json.Unmarshal([]byte(val), out)
}

func (c *Cache) SetSearch(ctx context.Context, origin, destination, dateKey string, v any) error {
	if !c.Enabled() {
		return nil
	}
	key := searchKey(origin, destination, dateKey)
	b, err := json.Marshal(v)
	if err != nil {
		return err
	}
	return c.client.Set(ctx, key, b, c.ttl).Err()
}

func (c *Cache) InvalidateFlight(ctx context.Context, id string) {
	if !c.Enabled() {
		return
	}
	_ = c.client.Del(ctx, flightKey(id)).Err()
}

func (c *Cache) InvalidateSearch(ctx context.Context, origin, destination, dateKey string) {
	if !c.Enabled() {
		return
	}
	_ = c.client.Del(ctx, searchKey(origin, destination, dateKey)).Err()
	_ = c.client.Del(ctx, searchKey(origin, destination, "any")).Err()
}

func flightKey(id string) string {
	return fmt.Sprintf("flight:%s", id)
}

func searchKey(origin, destination, dateKey string) string {
	return fmt.Sprintf("search:%s:%s:%s", origin, destination, dateKey)
}
