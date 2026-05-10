package store

import (
	"context"
	"errors"
	"time"

	flightv1 "github.com/aydar/soa-dz3/flight_service/proto"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

var (
	ErrNotFound      = errors.New("not found")
	ErrNoSeats       = errors.New("no seats")
	ErrAlreadyExists = errors.New("already exists")
)

type Store struct {
	pool *pgxpool.Pool
}

type Flight struct {
	ID             string
	Airline        string
	FlightNumber   string
	Origin         string
	Destination    string
	DepartureTime  time.Time
	ArrivalTime    time.Time
	TotalSeats     int
	AvailableSeats int
	PriceCents     int64
	Status         string
	Version        int64
}

type Reservation struct {
	ID        string
	FlightID  string
	BookingID string
	SeatCount int
	Status    string
	CreatedAt time.Time
	UpdatedAt time.Time
}

func New(pool *pgxpool.Pool) *Store {
	return &Store{pool: pool}
}

func (s *Store) SearchFlights(ctx context.Context, origin, destination string, date *time.Time) ([]Flight, error) {
	var rows pgx.Rows
	var err error

	if date != nil {
		rows, err = s.pool.Query(ctx, `
			SELECT id, airline, flight_number, origin, destination, departure_time, arrival_time,
			       total_seats, available_seats, price_cents, status, version
			FROM flights
			WHERE origin=$1 AND destination=$2 AND status='SCHEDULED' AND flight_date=$3
			ORDER BY departure_time
		`, origin, destination, *date)
	} else {
		rows, err = s.pool.Query(ctx, `
			SELECT id, airline, flight_number, origin, destination, departure_time, arrival_time,
			       total_seats, available_seats, price_cents, status, version
			FROM flights
			WHERE origin=$1 AND destination=$2 AND status='SCHEDULED'
			ORDER BY departure_time
		`, origin, destination)
	}
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	flights := make([]Flight, 0)
	for rows.Next() {
		var f Flight
		if err := rows.Scan(
			&f.ID, &f.Airline, &f.FlightNumber, &f.Origin, &f.Destination,
			&f.DepartureTime, &f.ArrivalTime, &f.TotalSeats, &f.AvailableSeats, &f.PriceCents, &f.Status, &f.Version,
		); err != nil {
			return nil, err
		}
		flights = append(flights, f)
	}
	return flights, rows.Err()
}

func (s *Store) GetFlight(ctx context.Context, id string) (Flight, error) {
	var f Flight
	row := s.pool.QueryRow(ctx, `
		SELECT id, airline, flight_number, origin, destination, departure_time, arrival_time,
		       total_seats, available_seats, price_cents, status, version
		FROM flights
		WHERE id=$1
	`, id)
	if err := row.Scan(
		&f.ID, &f.Airline, &f.FlightNumber, &f.Origin, &f.Destination,
		&f.DepartureTime, &f.ArrivalTime, &f.TotalSeats, &f.AvailableSeats, &f.PriceCents, &f.Status, &f.Version,
	); err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return Flight{}, ErrNotFound
		}
		return Flight{}, err
	}
	return f, nil
}

func (s *Store) ReserveSeats(ctx context.Context, flightID, bookingID string, seatCount int32) (Reservation, error) {
	tx, err := s.pool.BeginTx(ctx, pgx.TxOptions{})
	if err != nil {
		return Reservation{}, err
	}
	defer tx.Rollback(ctx)

	var available int
	var status string
	if err := tx.QueryRow(ctx, `
		SELECT available_seats, status
		FROM flights
		WHERE id=$1
		FOR UPDATE
	`, flightID).Scan(&available, &status); err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return Reservation{}, ErrNotFound
		}
		return Reservation{}, err
	}

	if status != "SCHEDULED" {
		return Reservation{}, ErrNotFound
	}

	if available < int(seatCount) {
		return Reservation{}, ErrNoSeats
	}

	var exists string
	if err := tx.QueryRow(ctx, `SELECT id FROM seat_reservations WHERE booking_id=$1`, bookingID).Scan(&exists); err == nil {
		return Reservation{}, ErrAlreadyExists
	} else if !errors.Is(err, pgx.ErrNoRows) {
		return Reservation{}, err
	}

	if _, err := tx.Exec(ctx, `
		UPDATE flights
		SET available_seats = available_seats - $1,
		    version = version + 1
		WHERE id=$2
	`, seatCount, flightID); err != nil {
		return Reservation{}, err
	}

	var r Reservation
	if err := tx.QueryRow(ctx, `
		INSERT INTO seat_reservations (flight_id, booking_id, seat_count, status)
		VALUES ($1, $2, $3, 'ACTIVE')
		RETURNING id, flight_id, booking_id, seat_count, status, created_at, updated_at
	`, flightID, bookingID, seatCount).Scan(
		&r.ID, &r.FlightID, &r.BookingID, &r.SeatCount, &r.Status, &r.CreatedAt, &r.UpdatedAt,
	); err != nil {
		return Reservation{}, err
	}

	if err := tx.Commit(ctx); err != nil {
		return Reservation{}, err
	}
	return r, nil
}

func (s *Store) ReleaseReservation(ctx context.Context, bookingID string) (Reservation, error) {
	tx, err := s.pool.BeginTx(ctx, pgx.TxOptions{})
	if err != nil {
		return Reservation{}, err
	}
	defer tx.Rollback(ctx)

	var r Reservation
	if err := tx.QueryRow(ctx, `
		SELECT id, flight_id, booking_id, seat_count, status, created_at, updated_at
		FROM seat_reservations
		WHERE booking_id=$1
		FOR UPDATE
	`, bookingID).Scan(
		&r.ID, &r.FlightID, &r.BookingID, &r.SeatCount, &r.Status, &r.CreatedAt, &r.UpdatedAt,
	); err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return Reservation{}, ErrNotFound
		}
		return Reservation{}, err
	}

	if r.Status != "ACTIVE" {
		return Reservation{}, ErrNotFound
	}

	if _, err := tx.Exec(ctx, `
		UPDATE flights
		SET available_seats = available_seats + $1,
		    version = version + 1
		WHERE id=$2
	`, r.SeatCount, r.FlightID); err != nil {
		return Reservation{}, err
	}

	if err := tx.QueryRow(ctx, `
		UPDATE seat_reservations
		SET status='RELEASED', updated_at=now()
		WHERE id=$1
		RETURNING id, flight_id, booking_id, seat_count, status, created_at, updated_at
	`, r.ID).Scan(
		&r.ID, &r.FlightID, &r.BookingID, &r.SeatCount, &r.Status, &r.CreatedAt, &r.UpdatedAt,
	); err != nil {
		return Reservation{}, err
	}

	if err := tx.Commit(ctx); err != nil {
		return Reservation{}, err
	}
	return r, nil
}

func FlightStatusToProto(status string) flightv1.FlightStatus {
	switch status {
	case "SCHEDULED":
		return flightv1.FlightStatus_FLIGHT_STATUS_SCHEDULED
	case "DEPARTED":
		return flightv1.FlightStatus_FLIGHT_STATUS_DEPARTED
	case "CANCELLED":
		return flightv1.FlightStatus_FLIGHT_STATUS_CANCELLED
	case "COMPLETED":
		return flightv1.FlightStatus_FLIGHT_STATUS_COMPLETED
	default:
		return flightv1.FlightStatus_FLIGHT_STATUS_UNSPECIFIED
	}
}

func ReservationStatusToProto(status string) flightv1.ReservationStatus {
	switch status {
	case "ACTIVE":
		return flightv1.ReservationStatus_RESERVATION_STATUS_ACTIVE
	case "RELEASED":
		return flightv1.ReservationStatus_RESERVATION_STATUS_RELEASED
	case "EXPIRED":
		return flightv1.ReservationStatus_RESERVATION_STATUS_EXPIRED
	default:
		return flightv1.ReservationStatus_RESERVATION_STATUS_UNSPECIFIED
	}
}
