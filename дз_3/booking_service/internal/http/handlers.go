package http

import (
	"encoding/json"
	"net/http"
	"time"

	"github.com/aydar/soa-dz3/booking_service/internal/grpcclient"
	"github.com/aydar/soa-dz3/booking_service/internal/store"
	flightv1 "github.com/aydar/soa-dz3/flight_service/proto"
	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/timestamppb"
)

type Handler struct {
	store  *store.Store
	flight *grpcclient.Client
}

func NewHandler(store *store.Store, flight *grpcclient.Client) *Handler {
	return &Handler{store: store, flight: flight}
}

type createBookingRequest struct {
	UserID         string `json:"user_id"`
	FlightID       string `json:"flight_id"`
	PassengerName  string `json:"passenger_name"`
	PassengerEmail string `json:"passenger_email"`
	SeatCount      int32  `json:"seat_count"`
}

type bookingResponse struct {
	ID              string    `json:"id"`
	UserID          string    `json:"user_id"`
	FlightID        string    `json:"flight_id"`
	PassengerName   string    `json:"passenger_name"`
	PassengerEmail  string    `json:"passenger_email"`
	SeatCount       int32     `json:"seat_count"`
	TotalPriceCents int64     `json:"total_price_cents"`
	Status          string    `json:"status"`
	CreatedAt       time.Time `json:"created_at"`
	UpdatedAt       time.Time `json:"updated_at"`
}

type flightResponse struct {
	ID             string    `json:"id"`
	Airline        string    `json:"airline"`
	FlightNumber   string    `json:"flight_number"`
	Origin         string    `json:"origin"`
	Destination    string    `json:"destination"`
	DepartureTime  time.Time `json:"departure_time"`
	ArrivalTime    time.Time `json:"arrival_time"`
	TotalSeats     int32     `json:"total_seats"`
	AvailableSeats int32     `json:"available_seats"`
	PriceCents     int64     `json:"price_cents"`
	Status         string    `json:"status"`
}

func (h *Handler) SearchFlights(w http.ResponseWriter, r *http.Request) {
	origin := r.URL.Query().Get("origin")
	destination := r.URL.Query().Get("destination")
	if origin == "" || destination == "" {
		writeError(w, http.StatusBadRequest, "origin и destination обязательны")
		return
	}

	var ts *timestamppb.Timestamp
	dateStr := r.URL.Query().Get("date")
	if dateStr != "" {
		date, err := time.Parse("2006-01-02", dateStr)
		if err != nil {
			writeError(w, http.StatusBadRequest, "неверная дата")
			return
		}
		ts = timestamppb.New(date)
	}

	resp, err := h.flight.SearchFlights(r.Context(), &flightv1.SearchFlightsRequest{
		Origin:        origin,
		Destination:   destination,
		DepartureDate: ts,
	})
	if err != nil {
		writeGrpcError(w, err)
		return
	}

	out := make([]flightResponse, 0, len(resp.Flights))
	for _, f := range resp.Flights {
		out = append(out, toFlightResponse(f))
	}

	writeJSON(w, http.StatusOK, out)
}

func (h *Handler) GetFlight(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "id")
	if !isValidUUID(id) {
		writeError(w, http.StatusBadRequest, "id должен быть UUID")
		return
	}
	resp, err := h.flight.GetFlight(r.Context(), &flightv1.GetFlightRequest{FlightId: id})
	if err != nil {
		writeGrpcError(w, err)
		return
	}

	writeJSON(w, http.StatusOK, toFlightResponse(resp.Flight))
}

func (h *Handler) CreateBooking(w http.ResponseWriter, r *http.Request) {
	var req createBookingRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "неверный json")
		return
	}
	if req.UserID == "" || req.FlightID == "" || req.PassengerName == "" || req.PassengerEmail == "" || req.SeatCount <= 0 {
		writeError(w, http.StatusBadRequest, "неверные поля")
		return
	}
	if !isValidUUID(req.FlightID) {
		writeError(w, http.StatusBadRequest, "flight_id должен быть UUID")
		return
	}

	flightResp, err := h.flight.GetFlight(r.Context(), &flightv1.GetFlightRequest{FlightId: req.FlightID})
	if err != nil {
		writeGrpcError(w, err)
		return
	}

	bookingID := uuid.NewString()
	_, err = h.flight.ReserveSeats(r.Context(), &flightv1.ReserveSeatsRequest{
		FlightId:  req.FlightID,
		BookingId: bookingID,
		SeatCount: req.SeatCount,
	})
	if err != nil {
		st, ok := status.FromError(err)
		if !ok || st.Code() != codes.AlreadyExists {
			writeGrpcError(w, err)
			return
		}
	}

	booking := store.Booking{
		ID:              bookingID,
		UserID:          req.UserID,
		FlightID:        req.FlightID,
		PassengerName:   req.PassengerName,
		PassengerEmail:  req.PassengerEmail,
		SeatCount:       int(req.SeatCount),
		TotalPriceCents: int64(req.SeatCount) * flightResp.Flight.PriceCents,
		Status:          "CONFIRMED",
	}

	created, err := h.store.CreateBooking(r.Context(), booking)
	if err != nil {
		_, _ = h.flight.ReleaseReservation(r.Context(), &flightv1.ReleaseReservationRequest{BookingId: bookingID})
		writeError(w, http.StatusInternalServerError, "ошибка создания")
		return
	}

	writeJSON(w, http.StatusCreated, toBookingResponse(created))
}

func (h *Handler) GetBooking(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "id")
	if !isValidUUID(id) {
		writeError(w, http.StatusBadRequest, "id должен быть UUID")
		return
	}
	booking, err := h.store.GetBooking(r.Context(), id)
	if err != nil {
		if err == store.ErrNotFound {
			writeError(w, http.StatusNotFound, "не найдено")
			return
		}
		writeError(w, http.StatusInternalServerError, "ошибка получения")
		return
	}
	writeJSON(w, http.StatusOK, toBookingResponse(booking))
}

func (h *Handler) CancelBooking(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "id")
	if !isValidUUID(id) {
		writeError(w, http.StatusBadRequest, "id должен быть UUID")
		return
	}
	booking, err := h.store.GetBooking(r.Context(), id)
	if err != nil {
		if err == store.ErrNotFound {
			writeError(w, http.StatusNotFound, "не найдено")
			return
		}
		writeError(w, http.StatusInternalServerError, "ошибка получения")
		return
	}
	if booking.Status != "CONFIRMED" {
		writeError(w, http.StatusBadRequest, "уже отменено")
		return
	}

	_, err = h.flight.ReleaseReservation(r.Context(), &flightv1.ReleaseReservationRequest{BookingId: id})
	if err != nil {
		writeGrpcError(w, err)
		return
	}

	updated, err := h.store.UpdateBookingStatus(r.Context(), id, "CANCELLED")
	if err != nil {
		writeError(w, http.StatusInternalServerError, "ошибка отмены")
		return
	}
	writeJSON(w, http.StatusOK, toBookingResponse(updated))
}

func (h *Handler) ListBookings(w http.ResponseWriter, r *http.Request) {
	userID := r.URL.Query().Get("user_id")
	if userID == "" {
		writeError(w, http.StatusBadRequest, "user_id обязателен")
		return
	}

	list, err := h.store.ListBookings(r.Context(), userID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "ошибка списка")
		return
	}

	out := make([]bookingResponse, 0, len(list))
	for _, b := range list {
		out = append(out, toBookingResponse(b))
	}
	writeJSON(w, http.StatusOK, out)
}

func toFlightResponse(f *flightv1.Flight) flightResponse {
	return flightResponse{
		ID:             f.GetId(),
		Airline:        f.GetAirline(),
		FlightNumber:   f.GetFlightNumber(),
		Origin:         f.GetOrigin(),
		Destination:    f.GetDestination(),
		DepartureTime:  f.GetDepartureTime().AsTime(),
		ArrivalTime:    f.GetArrivalTime().AsTime(),
		TotalSeats:     f.GetTotalSeats(),
		AvailableSeats: f.GetAvailableSeats(),
		PriceCents:     f.GetPriceCents(),
		Status:         f.GetStatus().String(),
	}
}

func toBookingResponse(b store.Booking) bookingResponse {
	return bookingResponse{
		ID:              b.ID,
		UserID:          b.UserID,
		FlightID:        b.FlightID,
		PassengerName:   b.PassengerName,
		PassengerEmail:  b.PassengerEmail,
		SeatCount:       int32(b.SeatCount),
		TotalPriceCents: b.TotalPriceCents,
		Status:          b.Status,
		CreatedAt:       b.CreatedAt,
		UpdatedAt:       b.UpdatedAt,
	}
}

func writeGrpcError(w http.ResponseWriter, err error) {
	st, ok := status.FromError(err)
	if !ok {
		writeError(w, http.StatusInternalServerError, "grpc ошибка")
		return
	}

	switch st.Code() {
	case codes.NotFound:
		writeError(w, http.StatusNotFound, st.Message())
	case codes.ResourceExhausted:
		writeError(w, http.StatusConflict, st.Message())
	case codes.AlreadyExists:
		writeError(w, http.StatusConflict, st.Message())
	case codes.InvalidArgument:
		writeError(w, http.StatusBadRequest, st.Message())
	case codes.Unavailable, codes.DeadlineExceeded:
		writeError(w, http.StatusServiceUnavailable, "сервис временно недоступен")
	default:
		writeError(w, http.StatusInternalServerError, st.Message())
	}
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}

func isValidUUID(v string) bool {
	_, err := uuid.Parse(v)
	return err == nil
}
