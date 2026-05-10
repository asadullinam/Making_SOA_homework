//go:build integration

package integration

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"testing"
	"time"
)

type flightListItem struct {
	ID string `json:"id"`
}

type flightDetails struct {
	ID             string `json:"id"`
	AvailableSeats int32  `json:"available_seats"`
}

type bookingResponse struct {
	ID     string `json:"id"`
	Status string `json:"status"`
}

type createBookingRequest struct {
	UserID         string `json:"user_id"`
	FlightID       string `json:"flight_id"`
	PassengerName  string `json:"passenger_name"`
	PassengerEmail string `json:"passenger_email"`
	SeatCount      int32  `json:"seat_count"`
}

func TestBookingFlow(t *testing.T) {
	client, baseURL := testClient()

	flightID := waitForFlight(t, client, baseURL)
	bookingID := createBooking(t, client, baseURL, flightID, 2)
	getBooking(t, client, baseURL, bookingID)
	cancelBooking(t, client, baseURL, bookingID)
	listBookings(t, client, baseURL)
}

func TestInvalidBookingPayload(t *testing.T) {
	client, baseURL := testClient()

	payload := []byte(`{"user_id":"","flight_id":"","seat_count":0}`)
	resp, err := client.Post(baseURL+"/bookings", "application/json", bytes.NewReader(payload))
	if err != nil {
		t.Fatalf("invalid payload: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusBadRequest {
		t.Fatalf("invalid payload: status %d", resp.StatusCode)
	}
}

func TestGetMissingBooking(t *testing.T) {
	client, baseURL := testClient()

	resp, err := client.Get(baseURL + "/bookings/00000000-0000-0000-0000-000000000000")
	if err != nil {
		t.Fatalf("missing booking: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusNotFound {
		t.Fatalf("missing booking: status %d", resp.StatusCode)
	}
}

func TestInsufficientSeats(t *testing.T) {
	client, baseURL := testClient()

	flightID := waitForFlight(t, client, baseURL)
	flight := getFlight(t, client, baseURL, flightID)
	seatCount := flight.AvailableSeats + 1

	payload := createBookingRequest{
		UserID:         "22222222-2222-2222-2222-222222222222",
		FlightID:       flightID,
		PassengerName:  "Ivan Petrov",
		PassengerEmail: "ivan@example.com",
		SeatCount:      seatCount,
	}
	resp := postJSON(t, client, baseURL+"/bookings", payload)
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusConflict {
		t.Fatalf("insufficient seats: status %d", resp.StatusCode)
	}
}

func TestCancelTwice(t *testing.T) {
	client, baseURL := testClient()

	flightID := waitForFlight(t, client, baseURL)
	bookingID := createBooking(t, client, baseURL, flightID, 1)
	cancelBooking(t, client, baseURL, bookingID)

	req, _ := http.NewRequest(http.MethodPost, baseURL+"/bookings/"+bookingID+"/cancel", nil)
	resp, err := client.Do(req)
	if err != nil {
		t.Fatalf("cancel twice: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusBadRequest {
		t.Fatalf("cancel twice: status %d", resp.StatusCode)
	}
}

func TestListBookingsEmpty(t *testing.T) {
	client, baseURL := testClient()

	url := baseURL + "/bookings?user_id=99999999-9999-9999-9999-999999999999"
	resp, err := client.Get(url)
	if err != nil {
		t.Fatalf("list empty: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Fatalf("list empty: status %d", resp.StatusCode)
	}
}

func testClient() (*http.Client, string) {
	baseURL := "http://localhost:8080"
	client := &http.Client{Timeout: 5 * time.Second}
	return client, baseURL
}

func waitForFlight(t *testing.T, client *http.Client, baseURL string) string {
	deadline := time.Now().Add(30 * time.Second)
	for time.Now().Before(deadline) {
		flights, err := getFlights(client, baseURL)
		if err == nil && len(flights) > 0 {
			return flights[0].ID
		}
		time.Sleep(500 * time.Millisecond)
	}
	t.Fatal("не удалось получить рейсы")
	return ""
}

func getFlights(client *http.Client, baseURL string) ([]flightListItem, error) {
	url := baseURL + "/flights?origin=SVO&destination=LED&date=2026-04-01"
	resp, err := client.Get(url)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	var flights []flightListItem
	if err := json.NewDecoder(resp.Body).Decode(&flights); err != nil {
		return nil, err
	}
	return flights, nil
}

func getFlight(t *testing.T, client *http.Client, baseURL, flightID string) flightDetails {
	resp, err := client.Get(baseURL + "/flights/" + flightID)
	if err != nil {
		t.Fatalf("get flight: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Fatalf("get flight: status %d", resp.StatusCode)
	}

	var out flightDetails
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		t.Fatalf("get flight decode: %v", err)
	}
	return out
}

func createBooking(t *testing.T, client *http.Client, baseURL, flightID string, seats int32) string {
	payload := createBookingRequest{
		UserID:         "11111111-1111-1111-1111-111111111111",
		FlightID:       flightID,
		PassengerName:  "Ivan Petrov",
		PassengerEmail: "ivan@example.com",
		SeatCount:      seats,
	}
	resp := postJSON(t, client, baseURL+"/bookings", payload)
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusCreated {
		body := readBody(resp)
		t.Fatalf("create booking: status %d body %s", resp.StatusCode, body)
	}

	var out bookingResponse
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		t.Fatalf("create booking decode: %v", err)
	}
	return out.ID
}

func getBooking(t *testing.T, client *http.Client, baseURL, bookingID string) {
	resp, err := client.Get(baseURL + "/bookings/" + bookingID)
	if err != nil {
		t.Fatalf("get booking: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body := readBody(resp)
		t.Fatalf("get booking: status %d body %s", resp.StatusCode, body)
	}
}

func cancelBooking(t *testing.T, client *http.Client, baseURL, bookingID string) {
	req, _ := http.NewRequest(http.MethodPost, baseURL+"/bookings/"+bookingID+"/cancel", nil)
	resp, err := client.Do(req)
	if err != nil {
		t.Fatalf("cancel booking: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body := readBody(resp)
		t.Fatalf("cancel booking: status %d body %s", resp.StatusCode, body)
	}
}

func listBookings(t *testing.T, client *http.Client, baseURL string) {
	url := baseURL + "/bookings?user_id=11111111-1111-1111-1111-111111111111"
	resp, err := client.Get(url)
	if err != nil {
		t.Fatalf("list bookings: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body := readBody(resp)
		t.Fatalf("list bookings: status %d body %s", resp.StatusCode, body)
	}
}

func postJSON(t *testing.T, client *http.Client, url string, payload any) *http.Response {
	data, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	resp, err := client.Post(url, "application/json", bytes.NewReader(data))
	if err != nil {
		t.Fatalf("post %s: %v", url, err)
	}
	return resp
}

func readBody(resp *http.Response) string {
	buf := new(bytes.Buffer)
	_, _ = buf.ReadFrom(resp.Body)
	return buf.String()
}

func (r bookingResponse) String() string {
	return fmt.Sprintf("booking(id=%s,status=%s)", r.ID, r.Status)
}
