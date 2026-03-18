package grpcserver

import (
	"context"
	"errors"
	"log"
	"time"

	"github.com/aydar/soa-dz3/flight_service/internal/cache"
	"github.com/aydar/soa-dz3/flight_service/internal/store"
	flightv1 "github.com/aydar/soa-dz3/flight_service/proto"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/timestamppb"
)

type Server struct {
	flightv1.UnimplementedFlightServiceServer
	store *store.Store
	cache *cache.Cache
}

func New(store *store.Store, cache *cache.Cache) *Server {
	return &Server{store: store, cache: cache}
}

func (s *Server) SearchFlights(ctx context.Context, req *flightv1.SearchFlightsRequest) (*flightv1.SearchFlightsResponse, error) {
	if req.GetOrigin() == "" || req.GetDestination() == "" {
		return nil, status.Error(codes.InvalidArgument, "origin/destination обязательны")
	}

	var date *time.Time
	dateKey := "any"
	if req.GetDepartureDate() != nil && req.GetDepartureDate().Seconds != 0 {
		t := req.GetDepartureDate().AsTime()
		d := time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, time.UTC)
		date = &d
		dateKey = d.Format("2006-01-02")
	}

	var cached []*flightv1.Flight
	if s.cache != nil {
		hit, err := s.cache.GetSearch(ctx, req.GetOrigin(), req.GetDestination(), dateKey, &cached)
		if err == nil && hit {
			log.Printf("cache hit search:%s:%s:%s", req.GetOrigin(), req.GetDestination(), dateKey)
			return &flightv1.SearchFlightsResponse{Flights: cached}, nil
		}
		if err == nil {
			log.Printf("cache miss search:%s:%s:%s", req.GetOrigin(), req.GetDestination(), dateKey)
		}
	}

	flights, err := s.store.SearchFlights(ctx, req.GetOrigin(), req.GetDestination(), date)
	if err != nil {
		return nil, status.Error(codes.Internal, "ошибка поиска")
	}

	maxVersion := int64(0)
	resp := &flightv1.SearchFlightsResponse{Flights: make([]*flightv1.Flight, 0, len(flights))}
	for _, f := range flights {
		if f.Version > maxVersion {
			maxVersion = f.Version
		}
		resp.Flights = append(resp.Flights, toProtoFlight(f))
	}

	if s.cache != nil {
		_ = s.cache.SetSearchIfNewer(ctx, req.GetOrigin(), req.GetDestination(), dateKey, maxVersion, resp.Flights)
	}
	return resp, nil
}

func (s *Server) GetFlight(ctx context.Context, req *flightv1.GetFlightRequest) (*flightv1.GetFlightResponse, error) {
	if req.GetFlightId() == "" {
		return nil, status.Error(codes.InvalidArgument, "flight_id обязателен")
	}

	var cached flightv1.Flight
	if s.cache != nil {
		hit, err := s.cache.GetFlight(ctx, req.GetFlightId(), &cached)
		if err == nil && hit {
			log.Printf("cache hit flight:%s", req.GetFlightId())
			return &flightv1.GetFlightResponse{Flight: &cached}, nil
		}
		if err == nil {
			log.Printf("cache miss flight:%s", req.GetFlightId())
		}
	}

	flight, err := s.store.GetFlight(ctx, req.GetFlightId())
	if err != nil {
		if errors.Is(err, store.ErrNotFound) {
			return nil, status.Error(codes.NotFound, "рейс не найден")
		}
		return nil, status.Error(codes.Internal, "ошибка получения")
	}
	resp := &flightv1.GetFlightResponse{Flight: toProtoFlight(flight)}
	if s.cache != nil {
		_ = s.cache.SetFlightIfNewer(ctx, req.GetFlightId(), flight.Version, resp.Flight)
	}
	return resp, nil
}

func (s *Server) ReserveSeats(ctx context.Context, req *flightv1.ReserveSeatsRequest) (*flightv1.ReserveSeatsResponse, error) {
	if req.GetFlightId() == "" || req.GetBookingId() == "" {
		return nil, status.Error(codes.InvalidArgument, "flight_id и booking_id обязательны")
	}
	if req.GetSeatCount() <= 0 {
		return nil, status.Error(codes.InvalidArgument, "seat_count должен быть > 0")
	}

	res, err := s.store.ReserveSeats(ctx, req.GetFlightId(), req.GetBookingId(), req.GetSeatCount())
	if err != nil {
		switch {
		case errors.Is(err, store.ErrNotFound):
			return nil, status.Error(codes.NotFound, "рейс не найден")
		case errors.Is(err, store.ErrNoSeats):
			return nil, status.Error(codes.ResourceExhausted, "нет мест")
		case errors.Is(err, store.ErrAlreadyExists):
			return nil, status.Error(codes.AlreadyExists, "резерв уже существует")
		default:
			return nil, status.Error(codes.Internal, "ошибка резерва")
		}
	}
	if s.cache != nil {
		s.cache.InvalidateFlight(ctx, req.GetFlightId())
		if f, err := s.store.GetFlight(ctx, req.GetFlightId()); err == nil {
			dateKey := f.DepartureTime.UTC().Format("2006-01-02")
			s.cache.InvalidateSearch(ctx, f.Origin, f.Destination, dateKey)
			_ = s.cache.SetFlightVersion(ctx, f.ID, f.Version)
			_ = s.cache.SetSearchVersion(ctx, f.Origin, f.Destination, dateKey, f.Version)
			_ = s.cache.SetSearchVersion(ctx, f.Origin, f.Destination, "any", f.Version)
		}
	}
	return &flightv1.ReserveSeatsResponse{Reservation: toProtoReservation(res)}, nil
}

func (s *Server) ReleaseReservation(ctx context.Context, req *flightv1.ReleaseReservationRequest) (*flightv1.ReleaseReservationResponse, error) {
	if req.GetBookingId() == "" {
		return nil, status.Error(codes.InvalidArgument, "booking_id обязателен")
	}

	res, err := s.store.ReleaseReservation(ctx, req.GetBookingId())
	if err != nil {
		if errors.Is(err, store.ErrNotFound) {
			return nil, status.Error(codes.NotFound, "резерв не найден")
		}
		return nil, status.Error(codes.Internal, "ошибка отмены")
	}
	if s.cache != nil {
		s.cache.InvalidateFlight(ctx, res.FlightID)
		if f, err := s.store.GetFlight(ctx, res.FlightID); err == nil {
			dateKey := f.DepartureTime.UTC().Format("2006-01-02")
			s.cache.InvalidateSearch(ctx, f.Origin, f.Destination, dateKey)
			_ = s.cache.SetFlightVersion(ctx, f.ID, f.Version)
			_ = s.cache.SetSearchVersion(ctx, f.Origin, f.Destination, dateKey, f.Version)
			_ = s.cache.SetSearchVersion(ctx, f.Origin, f.Destination, "any", f.Version)
		}
	}

	return &flightv1.ReleaseReservationResponse{Reservation: toProtoReservation(res)}, nil
}

func toProtoFlight(f store.Flight) *flightv1.Flight {
	return &flightv1.Flight{
		Id:             f.ID,
		Airline:        f.Airline,
		FlightNumber:   f.FlightNumber,
		Origin:         f.Origin,
		Destination:    f.Destination,
		DepartureTime:  timestamppb.New(f.DepartureTime),
		ArrivalTime:    timestamppb.New(f.ArrivalTime),
		TotalSeats:     int32(f.TotalSeats),
		AvailableSeats: int32(f.AvailableSeats),
		PriceCents:     f.PriceCents,
		Status:         store.FlightStatusToProto(f.Status),
	}
}

func toProtoReservation(r store.Reservation) *flightv1.SeatReservation {
	return &flightv1.SeatReservation{
		Id:        r.ID,
		FlightId:  r.FlightID,
		BookingId: r.BookingID,
		SeatCount: int32(r.SeatCount),
		Status:    store.ReservationStatusToProto(r.Status),
		CreatedAt: timestamppb.New(r.CreatedAt),
		UpdatedAt: timestamppb.New(r.UpdatedAt),
	}
}
