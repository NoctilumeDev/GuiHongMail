package platform

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"
)

type RouteRegistrar func(*http.ServeMux, *Runtime)
type BackgroundService func(context.Context, *Runtime) error

func RunService(role string, register RouteRegistrar, background BackgroundService) error {
	runtime, err := NewRuntime(role)
	if err != nil {
		return err
	}
	defer runtime.Close()
	ctx, cancelSignal := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancelSignal()
	ctx, cancel := context.WithCancel(ctx)
	defer cancel()
	mux := http.NewServeMux()
	server := &http.Server{
		Addr:              runtime.Config.HTTPAddress,
		Handler:           securityHeaders(mux),
		ReadHeaderTimeout: 3 * time.Second,
		ReadTimeout:       10 * time.Second,
		WriteTimeout:      10 * time.Second,
		IdleTimeout:       30 * time.Second,
		MaxHeaderBytes:    16 * 1024,
	}
	registerFoundation(mux, runtime, func() {
		runtime.Drain()
		go func() {
			time.Sleep(150 * time.Millisecond)
			cancel()
		}()
	})
	if register != nil {
		register(mux, runtime)
	}
	errorsChannel := make(chan error, 2)
	go func() {
		log.Printf("service=%s source=%s http=%s", role, runtime.Config.SourceSHA, runtime.Config.HTTPAddress)
		failure := server.ListenAndServe()
		if failure != nil && !errors.Is(failure, http.ErrServerClosed) {
			errorsChannel <- failure
		}
	}()
	if background != nil {
		go func() {
			if failure := background(ctx, runtime); failure != nil && ctx.Err() == nil {
				errorsChannel <- failure
			}
		}()
	}
	select {
	case <-ctx.Done():
	case failure := <-errorsChannel:
		cancel()
		shutdownContext, shutdownCancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer shutdownCancel()
		_ = server.Shutdown(shutdownContext)
		return failure
	}
	runtime.Drain()
	shutdownContext, shutdownCancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer shutdownCancel()
	return server.Shutdown(shutdownContext)
}

func registerFoundation(mux *http.ServeMux, runtime *Runtime, shutdown func()) {
	mux.HandleFunc("GET /health/live", func(writer http.ResponseWriter, _ *http.Request) {
		writeJSON(writer, http.StatusOK, map[string]any{"service": runtime.Config.Role, "alive": true})
	})
	mux.HandleFunc("GET /health/ready", func(writer http.ResponseWriter, request *http.Request) {
		readiness, ready := runtime.Ready(request.Context())
		status := http.StatusOK
		if !ready {
			status = http.StatusServiceUnavailable
		}
		writeJSON(writer, status, readiness)
	})
	mux.Handle("GET /internal/identity", internal(runtime, http.HandlerFunc(func(writer http.ResponseWriter, _ *http.Request) {
		writeJSON(writer, http.StatusOK, runtime.Identity())
	})))
	mux.Handle("POST /internal/drain", internal(runtime, http.HandlerFunc(func(writer http.ResponseWriter, _ *http.Request) {
		runtime.Drain()
		writeJSON(writer, http.StatusOK, map[string]any{"service": runtime.Config.Role, "state": "DRAINING"})
	})))
	mux.Handle("POST /internal/shutdown", internal(runtime, http.HandlerFunc(func(writer http.ResponseWriter, _ *http.Request) {
		runtime.Drain()
		writeJSON(writer, http.StatusAccepted, map[string]any{"service": runtime.Config.Role, "state": "DRAINING"})
		shutdown()
	})))
	mux.Handle("POST /internal/storage/objects", internal(runtime, http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		var input struct {
			ObjectID  string `json:"objectId"`
			Authority string `json:"authority"`
			Base64    string `json:"base64"`
		}
		if err := decodeJSON(request, &input, 7*1024*1024); err != nil || len(input.Base64) > 7*1024*1024 {
			writeError(writer, http.StatusBadRequest, "INVALID_STORAGE_REQUEST")
			return
		}
		data, err := base64.StdEncoding.DecodeString(input.Base64)
		if err != nil {
			writeError(writer, http.StatusBadRequest, "INVALID_STORAGE_REQUEST")
			return
		}
		blob, err := runtime.Objects.Stage(request.Context(), input.ObjectID, input.Authority, data)
		if err != nil {
			log.Printf("storage stage failed closed: %v", err)
			writeError(writer, http.StatusServiceUnavailable, "STORAGE_OPERATION_UNCONFIRMED")
			return
		}
		writeJSON(writer, http.StatusOK, blob)
	})))
	mux.Handle("POST /internal/storage/objects/{id}/references", internal(runtime, http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		var input struct {
			Kind        string `json:"kind"`
			ReferenceID string `json:"referenceId"`
		}
		if err := decodeJSON(request, &input, 4096); err != nil {
			writeError(writer, http.StatusBadRequest, "INVALID_STORAGE_REQUEST")
			return
		}
		blob, err := runtime.Objects.Reference(request.Context(), request.PathValue("id"), input.Kind, input.ReferenceID)
		if err != nil {
			log.Printf("storage reference failed closed: %v", err)
			writeError(writer, http.StatusServiceUnavailable, "STORAGE_OPERATION_UNCONFIRMED")
			return
		}
		writeJSON(writer, http.StatusOK, blob)
	})))
	mux.Handle("DELETE /internal/storage/objects/{id}/references", internal(runtime, http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		var input struct {
			Kind        string `json:"kind"`
			ReferenceID string `json:"referenceId"`
		}
		if err := decodeJSON(request, &input, 4096); err != nil {
			writeError(writer, http.StatusBadRequest, "INVALID_STORAGE_REQUEST")
			return
		}
		if err := runtime.Objects.Dereference(request.Context(), request.PathValue("id"), input.Kind, input.ReferenceID); err != nil {
			log.Printf("storage dereference failed closed: %v", err)
			writeError(writer, http.StatusServiceUnavailable, "STORAGE_OPERATION_UNCONFIRMED")
			return
		}
		writer.WriteHeader(http.StatusNoContent)
	})))
	mux.Handle("GET /internal/storage/objects/{id}", internal(runtime, http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		data, err := runtime.Objects.Read(request.Context(), request.PathValue("id"))
		if err != nil {
			log.Printf("storage read failed closed: %v", err)
			writeError(writer, http.StatusServiceUnavailable, "STORAGE_OPERATION_UNCONFIRMED")
			return
		}
		writer.Header().Set("Content-Type", "application/octet-stream")
		writer.WriteHeader(http.StatusOK)
		_, _ = writer.Write(data)
	})))
	mux.Handle("POST /internal/storage/gc", internal(runtime, http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		deleted, err := runtime.Objects.GC(request.Context())
		if err != nil {
			log.Printf("storage GC failed closed: %v", err)
			writeError(writer, http.StatusServiceUnavailable, "STORAGE_OPERATION_UNCONFIRMED")
			return
		}
		writeJSON(writer, http.StatusOK, map[string]any{"deleted": deleted})
	})))
}

func internal(runtime *Runtime, next http.Handler) http.Handler {
	return http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		if err := runtime.RequireInternal(request.Header.Get("X-GuiHong-Service"), request.Header.Get("Authorization")); err != nil {
			writeError(writer, http.StatusUnauthorized, "INTERNAL_AUTH_REQUIRED")
			return
		}
		next.ServeHTTP(writer, request)
	})
}

func securityHeaders(next http.Handler) http.Handler {
	return http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		writer.Header().Set("X-Content-Type-Options", "nosniff")
		writer.Header().Set("X-Frame-Options", "DENY")
		writer.Header().Set("Referrer-Policy", "no-referrer")
		if strings.HasPrefix(request.URL.Path, "/api/") || strings.HasPrefix(request.URL.Path, "/internal/") || strings.HasPrefix(request.URL.Path, "/health/") {
			writer.Header().Set("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
		} else {
			writer.Header().Set("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-src 'self' blob:; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
		}
		writer.Header().Set("Cache-Control", "no-store")
		next.ServeHTTP(writer, request)
	})
}

func decodeJSON(request *http.Request, target any, limit int64) error {
	reader := http.MaxBytesReader(nil, request.Body, limit)
	decoder := json.NewDecoder(reader)
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(target); err != nil {
		return err
	}
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		return fmt.Errorf("request must contain exactly one JSON value")
	}
	return nil
}

func writeJSON(writer http.ResponseWriter, status int, value any) {
	writer.Header().Set("Content-Type", "application/json;charset=UTF-8")
	writer.WriteHeader(status)
	_ = json.NewEncoder(writer).Encode(value)
}

func writeError(writer http.ResponseWriter, status int, code string) {
	writeJSON(writer, status, map[string]string{"code": code})
}

func bearerCookie(request *http.Request, name string) string {
	cookie, err := request.Cookie(name)
	if err != nil || strings.TrimSpace(cookie.Value) == "" {
		return ""
	}
	return cookie.Value
}
