CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS bookings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  flight_id uuid NOT NULL,
  passenger_name varchar NOT NULL,
  passenger_email varchar NOT NULL,
  seat_count int NOT NULL CHECK (seat_count > 0),
  total_price_cents int NOT NULL CHECK (total_price_cents > 0),
  status varchar NOT NULL CHECK (status IN ('CONFIRMED', 'CANCELLED')),
  created_at timestamp NOT NULL DEFAULT now(),
  updated_at timestamp NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS bookings_user_id_idx ON bookings(user_id);
