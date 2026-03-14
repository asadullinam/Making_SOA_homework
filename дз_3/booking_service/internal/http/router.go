package http

import "github.com/go-chi/chi/v5"

func NewRouter(h *Handler) *chi.Mux {
	r := chi.NewRouter()

	r.Get("/flights", h.SearchFlights)
	r.Get("/flights/{id}", h.GetFlight)

	r.Post("/bookings", h.CreateBooking)
	r.Get("/bookings/{id}", h.GetBooking)
	r.Post("/bookings/{id}/cancel", h.CancelBooking)
	r.Get("/bookings", h.ListBookings)

	return r
}
