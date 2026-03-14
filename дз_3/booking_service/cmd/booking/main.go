package main

import (
	"context"
	"log"
	"net/http"
	"time"

	"github.com/aydar/soa-dz3/booking_service/internal/config"
	"github.com/aydar/soa-dz3/booking_service/internal/db"
	"github.com/aydar/soa-dz3/booking_service/internal/grpcclient"
	httpapi "github.com/aydar/soa-dz3/booking_service/internal/http"
	"github.com/aydar/soa-dz3/booking_service/internal/store"
)

func main() {
	cfg := config.Load()
	if err := db.RunMigrations(cfg.DBURL, cfg.MigrationsPath); err != nil {
		log.Fatalf("миграции: %v", err)
	}

	ctx := context.Background()
	pool, err := db.NewPool(ctx, cfg.DBURL)
	if err != nil {
		log.Fatalf("db: %v", err)
	}
	defer pool.Close()

	flightClient, err := grpcclient.New(cfg.FlightGRPCAddr, cfg.FlightAPIKey, grpcclient.CBConfig{
		FailureThreshold: cfg.CBFailureThreshold,
		OpenTimeout:      time.Duration(cfg.CBOpenSeconds) * time.Second,
	})
	if err != nil {
		log.Fatalf("grpc: %v", err)
	}
	defer flightClient.Close()

	store := store.New(pool)
	h := httpapi.NewHandler(store, flightClient)
	r := httpapi.NewRouter(h)

	log.Printf("booking service на %s", cfg.HTTPAddr)
	log.Fatal(http.ListenAndServe(cfg.HTTPAddr, r))
}
