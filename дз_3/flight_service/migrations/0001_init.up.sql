CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS flights (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  airline varchar NOT NULL,
  flight_number varchar NOT NULL,
  origin char(3) NOT NULL,
  destination char(3) NOT NULL,
  departure_time timestamp NOT NULL,
  arrival_time timestamp NOT NULL,
  total_seats int NOT NULL CHECK (total_seats > 0),
  available_seats int NOT NULL CHECK (available_seats >= 0),
  price_cents int NOT NULL CHECK (price_cents > 0),
  status varchar NOT NULL CHECK (status IN ('SCHEDULED', 'DEPARTED', 'CANCELLED', 'COMPLETED')),
  flight_date date NOT NULL,
  CONSTRAINT flight_unique UNIQUE (flight_number, flight_date),
  CHECK (available_seats <= total_seats)
);

CREATE TABLE IF NOT EXISTS seat_reservations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  flight_id uuid NOT NULL REFERENCES flights(id) ON DELETE CASCADE,
  booking_id uuid NOT NULL UNIQUE,
  seat_count int NOT NULL CHECK (seat_count > 0),
  status varchar NOT NULL CHECK (status IN ('ACTIVE', 'RELEASED', 'EXPIRED')),
  created_at timestamp NOT NULL DEFAULT now(),
  updated_at timestamp NOT NULL DEFAULT now()
);
