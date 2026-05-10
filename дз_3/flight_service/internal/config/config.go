package config

import (
	"os"
	"strconv"
	"strings"
	"time"
)

type Config struct {
	DBURL          string
	GRPCAddr       string
	MigrationsPath string
	APIKey         string
	RedisMode      string
	RedisAddr      string
	RedisSentinels []string
	RedisMaster    string
	CacheTTL       time.Duration
}

func Load() Config {
	return Config{
		DBURL:          getEnv("DB_URL", "postgres://flight_user:flight_pass@localhost:5433/flight_db?sslmode=disable"),
		GRPCAddr:       getEnv("GRPC_ADDR", ":50051"),
		MigrationsPath: getEnv("MIGRATIONS_PATH", "file://./flight_service/migrations"),
		APIKey:         getEnv("GRPC_API_KEY", "dev-key"),
		RedisMode:      getEnv("REDIS_MODE", "single"),
		RedisAddr:      getEnv("REDIS_ADDR", ""),
		RedisSentinels: splitEnv("REDIS_SENTINELS"),
		RedisMaster:    getEnv("REDIS_MASTER_NAME", "mymaster"),
		CacheTTL:       getDurationEnv("CACHE_TTL_SECONDS", 600),
	}
}

func getEnv(key, def string) string {
	val := os.Getenv(key)
	if val == "" {
		return def
	}
	return val
}

func getDurationEnv(key string, defSeconds int) time.Duration {
	val := os.Getenv(key)
	if val == "" {
		return time.Duration(defSeconds) * time.Second
	}
	parsed, err := strconv.Atoi(val)
	if err != nil {
		return time.Duration(defSeconds) * time.Second
	}
	return time.Duration(parsed) * time.Second
}

func splitEnv(key string) []string {
	val := strings.TrimSpace(os.Getenv(key))
	if val == "" {
		return nil
	}
	parts := strings.Split(val, ",")
	out := make([]string, 0, len(parts))
	for _, p := range parts {
		p = strings.TrimSpace(p)
		if p != "" {
			out = append(out, p)
		}
	}
	return out
}
