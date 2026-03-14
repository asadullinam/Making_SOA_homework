package config

import (
	"os"
	"strconv"
)

type Config struct {
	DBURL              string
	HTTPAddr           string
	FlightGRPCAddr     string
	MigrationsPath     string
	FlightAPIKey       string
	CBFailureThreshold int
	CBOpenSeconds      int
}

func Load() Config {
	return Config{
		DBURL:              getEnv("DB_URL", "postgres://booking_user:booking_pass@localhost:5434/booking_db?sslmode=disable"),
		HTTPAddr:           getEnv("HTTP_ADDR", ":8080"),
		FlightGRPCAddr:     getEnv("FLIGHT_GRPC_ADDR", "localhost:50051"),
		MigrationsPath:     getEnv("MIGRATIONS_PATH", "file://./booking_service/migrations"),
		FlightAPIKey:       getEnv("FLIGHT_API_KEY", "dev-key"),
		CBFailureThreshold: getEnvInt("CB_FAILURE_THRESHOLD", 5),
		CBOpenSeconds:      getEnvInt("CB_OPEN_SECONDS", 20),
	}
}

func getEnv(key, def string) string {
	val := os.Getenv(key)
	if val == "" {
		return def
	}
	return val
}

func getEnvInt(key string, def int) int {
	val := os.Getenv(key)
	if val == "" {
		return def
	}
	parsed, err := strconv.Atoi(val)
	if err != nil {
		return def
	}
	return parsed
}
