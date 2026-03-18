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

const setIfNewerScript = `
local current = redis.call("GET", KEYS[2])
if (not current) or (tonumber(ARGV[1]) >= tonumber(current)) then
	redis.call("SET", KEYS[1], ARGV[2], "PX", ARGV[3])
	redis.call("SET", KEYS[2], ARGV[1], "PX", ARGV[3])
	return 1
end
return 0
`

const setVersionIfNewerScript = `
local current = redis.call("GET", KEYS[1])
if (not current) or (tonumber(ARGV[1]) >= tonumber(current)) then
	redis.call("SET", KEYS[1], ARGV[1], "PX", ARGV[2])
	return 1
end
return 0
`

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

func (c *Cache) SetFlightIfNewer(ctx context.Context, id string, version int64, v any) error {
	if !c.Enabled() {
		return nil
	}
	key := flightKey(id)
	verKey := flightVersionKey(id)
	b, err := json.Marshal(v)
	if err != nil {
		return err
	}
	return c.setIfNewer(ctx, key, verKey, version, b)
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

func (c *Cache) SetSearchIfNewer(ctx context.Context, origin, destination, dateKey string, version int64, v any) error {
	if !c.Enabled() {
		return nil
	}
	key := searchKey(origin, destination, dateKey)
	verKey := searchVersionKey(origin, destination, dateKey)
	b, err := json.Marshal(v)
	if err != nil {
		return err
	}
	return c.setIfNewer(ctx, key, verKey, version, b)
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

func (c *Cache) SetFlightVersion(ctx context.Context, id string, version int64) error {
	if !c.Enabled() {
		return nil
	}
	return c.setVersionIfNewer(ctx, flightVersionKey(id), version)
}

func (c *Cache) SetSearchVersion(ctx context.Context, origin, destination, dateKey string, version int64) error {
	if !c.Enabled() {
		return nil
	}
	return c.setVersionIfNewer(ctx, searchVersionKey(origin, destination, dateKey), version)
}

func (c *Cache) setIfNewer(ctx context.Context, key, verKey string, version int64, payload []byte) error {
	ttlMs := c.ttl.Milliseconds()
	_, err := c.client.Eval(ctx, setIfNewerScript, []string{key, verKey}, version, payload, ttlMs).Result()
	return err
}

func (c *Cache) setVersionIfNewer(ctx context.Context, verKey string, version int64) error {
	ttlMs := c.ttl.Milliseconds()
	_, err := c.client.Eval(ctx, setVersionIfNewerScript, []string{verKey}, version, ttlMs).Result()
	return err
}

func flightKey(id string) string {
	return fmt.Sprintf("flight:%s", id)
}

func flightVersionKey(id string) string {
	return fmt.Sprintf("flight:%s:version", id)
}

func searchKey(origin, destination, dateKey string) string {
	return fmt.Sprintf("search:%s:%s:%s", origin, destination, dateKey)
}

func searchVersionKey(origin, destination, dateKey string) string {
	return fmt.Sprintf("search:%s:%s:%s:version", origin, destination, dateKey)
}
