package grpcserver

import (
	"context"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
)

func AuthInterceptor(apiKey string) grpc.UnaryServerInterceptor {
	return func(ctx context.Context, req any, _ *grpc.UnaryServerInfo, handler grpc.UnaryHandler) (any, error) {
		if apiKey == "" {
			return nil, status.Error(codes.Unauthenticated, "api key не задан")
		}
		md, ok := metadata.FromIncomingContext(ctx)
		if !ok {
			return nil, status.Error(codes.Unauthenticated, "нет метаданных")
		}
		vals := md.Get("x-api-key")
		if len(vals) == 0 || vals[0] != apiKey {
			return nil, status.Error(codes.Unauthenticated, "неверный api key")
		}
		return handler(ctx, req)
	}
}
