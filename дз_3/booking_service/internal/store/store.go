package store

import (
	"context"
	"errors"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

var ErrNotFound = errors.New("not found")

type Store struct {
	pool *pgxpool.Pool
}

type Booking struct {
	ID              string
	UserID          string
	FlightID        string
	PassengerName   string
	PassengerEmail  string
	SeatCount       int
	TotalPriceCents int64
	Status          string
	CreatedAt       time.Time
	UpdatedAt       time.Time
}

func New(pool *pgxpool.Pool) *Store {
	return &Store{pool: pool}
}

func (s *Store) CreateBooking(ctx context.Context, b Booking) (Booking, error) {
	row := s.pool.QueryRow(ctx, `
		INSERT INTO bookings (id, user_id, flight_id, passenger_name, passenger_email, seat_count, total_price_cents, status)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
		RETURNING id, user_id, flight_id, passenger_name, passenger_email, seat_count, total_price_cents, status, created_at, updated_at
	`, b.ID, b.UserID, b.FlightID, b.PassengerName, b.PassengerEmail, b.SeatCount, b.TotalPriceCents, b.Status)

	var out Booking
	if err := row.Scan(
		&out.ID, &out.UserID, &out.FlightID, &out.PassengerName, &out.PassengerEmail,
		&out.SeatCount, &out.TotalPriceCents, &out.Status, &out.CreatedAt, &out.UpdatedAt,
	); err != nil {
		return Booking{}, err
	}
	return out, nil
}

func (s *Store) GetBooking(ctx context.Context, id string) (Booking, error) {
	row := s.pool.QueryRow(ctx, `
		SELECT id, user_id, flight_id, passenger_name, passenger_email, seat_count, total_price_cents, status, created_at, updated_at
		FROM bookings
		WHERE id=$1
	`, id)

	var out Booking
	if err := row.Scan(
		&out.ID, &out.UserID, &out.FlightID, &out.PassengerName, &out.PassengerEmail,
		&out.SeatCount, &out.TotalPriceCents, &out.Status, &out.CreatedAt, &out.UpdatedAt,
	); err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return Booking{}, ErrNotFound
		}
		return Booking{}, err
	}
	return out, nil
}

func (s *Store) UpdateBookingStatus(ctx context.Context, id, status string) (Booking, error) {
	row := s.pool.QueryRow(ctx, `
		UPDATE bookings
		SET status=$1, updated_at=now()
		WHERE id=$2
		RETURNING id, user_id, flight_id, passenger_name, passenger_email, seat_count, total_price_cents, status, created_at, updated_at
	`, status, id)

	var out Booking
	if err := row.Scan(
		&out.ID, &out.UserID, &out.FlightID, &out.PassengerName, &out.PassengerEmail,
		&out.SeatCount, &out.TotalPriceCents, &out.Status, &out.CreatedAt, &out.UpdatedAt,
	); err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return Booking{}, ErrNotFound
		}
		return Booking{}, err
	}
	return out, nil
}

func (s *Store) ListBookings(ctx context.Context, userID string) ([]Booking, error) {
	rows, err := s.pool.Query(ctx, `
		SELECT id, user_id, flight_id, passenger_name, passenger_email, seat_count, total_price_cents, status, created_at, updated_at
		FROM bookings
		WHERE user_id=$1
		ORDER BY created_at DESC
	`, userID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	list := make([]Booking, 0)
	for rows.Next() {
		var out Booking
		if err := rows.Scan(
			&out.ID, &out.UserID, &out.FlightID, &out.PassengerName, &out.PassengerEmail,
			&out.SeatCount, &out.TotalPriceCents, &out.Status, &out.CreatedAt, &out.UpdatedAt,
		); err != nil {
			return nil, err
		}
		list = append(list, out)
	}
	return list, rows.Err()
}
