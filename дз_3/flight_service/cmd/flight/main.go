package main

import (
	"context"
	"log"
	"net"

	"github.com/aydar/soa-dz3/flight_service/internal/cache"
	"github.com/aydar/soa-dz3/flight_service/internal/config"
	"github.com/aydar/soa-dz3/flight_service/internal/db"
	"github.com/aydar/soa-dz3/flight_service/internal/grpcserver"
	"github.com/aydar/soa-dz3/flight_service/internal/store"
	flightv1 "github.com/aydar/soa-dz3/flight_service/proto"
	"google.golang.org/grpc"
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

	storeRepo := store.New(pool)
	cacheRepo := cache.New(cache.Config{
		Mode:      cfg.RedisMode,
		Addr:      cfg.RedisAddr,
		Sentinels: cfg.RedisSentinels,
		Master:    cfg.RedisMaster,
		TTL:       cfg.CacheTTL,
	})
	grpcSrv := grpc.NewServer(grpc.UnaryInterceptor(grpcserver.AuthInterceptor(cfg.APIKey)))
	flightv1.RegisterFlightServiceServer(grpcSrv, grpcserver.New(storeRepo, cacheRepo))

	lis, err := net.Listen("tcp", cfg.GRPCAddr)
	if err != nil {
		log.Fatalf("listen: %v", err)
	}

	log.Printf("flight service на %s", cfg.GRPCAddr)
	log.Fatal(grpcSrv.Serve(lis))
}
