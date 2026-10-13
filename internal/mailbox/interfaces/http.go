package interfaces

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"time"

	"github.com/NoctilumeDev/GuiHongMail/internal/mailbox/application"
	"github.com/NoctilumeDev/GuiHongMail/internal/mailbox/domain"
	"github.com/NoctilumeDev/GuiHongMail/internal/platform"
)

const approvedOrigin = "http://127.0.0.1:18080"

type principalKey struct{}

func Register(mux *http.ServeMux, runtime *platform.Runtime, identity *application.Identity) {
	mux.HandleFunc("POST /api/auth/login", origin(func(writer http.ResponseWriter, request *http.Request) {
		var input struct {
			Address  string `json:"address"`
			Password string `json:"password"`
		}
		if err := decode(request, &input); err != nil {
			apiError(writer, http.StatusBadRequest, "REQUEST_MALFORMED")
			return
		}
		client, _, _ := net.SplitHostPort(request.RemoteAddr)
		if client == "" {
			client = request.RemoteAddr
		}
		session, err := identity.Login(request.Context(), input.Address, input.Password, client)
		if err != nil {
			identityError(writer, err)
			return
		}
		writeSession(writer, session)
	}))
	mux.Handle("GET /api/auth/me", authenticated(identity, false, http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		writeAPI(writer, http.StatusOK, user(principal(request)))
	})))
	mux.Handle("GET /api/accounts/{id}", authenticated(identity, false, http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		current := principal(request)
		if request.PathValue("id") != current.AccountID {
			apiError(writer, http.StatusNotFound, "RESOURCE_NOT_FOUND")
			return
		}
		writeAPI(writer, http.StatusOK, user(current))
	})))
	mux.Handle("POST /api/auth/refresh", authenticated(identity, true, http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		session, err := identity.Refresh(request.Context(), principal(request))
		if err != nil {
			identityError(writer, err)
			return
		}
		writeSession(writer, session)
	})))
	mux.Handle("POST /api/auth/logout", authenticated(identity, true, http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		if err := identity.Logout(request.Context(), principal(request)); err != nil {
			identityError(writer, err)
			return
		}
		http.SetCookie(writer, &http.Cookie{Name: "guihong_session", Value: "", Path: "/api", HttpOnly: true,
			SameSite: http.SameSiteStrictMode, MaxAge: -1, Expires: time.Unix(1, 0)})
		writer.WriteHeader(http.StatusNoContent)
	})))
	mux.Handle("POST /internal/accounts", internal(runtime, http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		var input struct {
			Address     string `json:"address"`
			Password    string `json:"password"`
			DisplayName string `json:"displayName"`
		}
		if err := decode(request, &input); err != nil {
			apiError(writer, http.StatusBadRequest, "REQUEST_MALFORMED")
			return
		}
		id, err := identity.Provision(request.Context(), input.Address, input.Password, input.DisplayName)
		if err != nil {
			if errors.Is(err, application.ErrInvalidAccount) {
				apiError(writer, http.StatusBadRequest, "INVALID_ACCOUNT")
			} else {
				identityError(writer, err)
			}
			return
		}
		writeAPI(writer, http.StatusOK, map[string]string{"account_id": id})
	})))
	mux.Handle("POST /internal/accounts/{id}/enabled", internal(runtime, http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		var input struct {
			Enabled bool `json:"enabled"`
		}
		if err := decode(request, &input); err != nil {
			apiError(writer, http.StatusBadRequest, "REQUEST_MALFORMED")
			return
		}
		if err := identity.SetEnabled(request.Context(), request.PathValue("id"), input.Enabled); err != nil {
			identityError(writer, err)
			return
		}
		writer.WriteHeader(http.StatusNoContent)
	})))
}

func authenticated(identity *application.Identity, write bool, next http.Handler) http.Handler {
	return http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		if write && request.Header.Get("Origin") != approvedOrigin {
			apiError(writer, http.StatusForbidden, "ORIGIN_REJECTED")
			return
		}
		cookie, err := request.Cookie("guihong_session")
		if err != nil {
			apiError(writer, http.StatusUnauthorized, "AUTHENTICATION_REQUIRED")
			return
		}
		current, err := identity.Authenticate(request.Context(), cookie.Value)
		if err != nil {
			identityError(writer, err)
			return
		}
		if current == nil {
			apiError(writer, http.StatusUnauthorized, "AUTHENTICATION_REQUIRED")
			return
		}
		if write {
			csrf := request.Header.Get("X-GuiHong-CSRF")
			if csrf == "" || !platform.Same(platform.SHA256([]byte(csrf)), current.CSRFHash) {
				apiError(writer, http.StatusForbidden, "CSRF_REJECTED")
				return
			}
		}
		next.ServeHTTP(writer, request.WithContext(context.WithValue(request.Context(), principalKey{}, *current)))
	})
}

func origin(next http.HandlerFunc) http.HandlerFunc {
	return func(writer http.ResponseWriter, request *http.Request) {
		if request.Header.Get("Origin") != approvedOrigin {
			apiError(writer, http.StatusForbidden, "ORIGIN_REJECTED")
			return
		}
		next(writer, request)
	}
}

func internal(runtime *platform.Runtime, next http.Handler) http.Handler {
	return http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		if err := runtime.RequireInternal(request.Header.Get("X-GuiHong-Service"), request.Header.Get("Authorization")); err != nil {
			apiError(writer, http.StatusUnauthorized, "INTERNAL_AUTH_REQUIRED")
			return
		}
		next.ServeHTTP(writer, request)
	})
}

func principal(request *http.Request) domain.Principal {
	return request.Context().Value(principalKey{}).(domain.Principal)
}

func user(principal domain.Principal) map[string]string {
	return map[string]string{"account_id": principal.AccountID, "address": principal.Address,
		"display_name": principal.DisplayName, "role": principal.Role}
}

func writeSession(writer http.ResponseWriter, session application.Session) {
	http.SetCookie(writer, &http.Cookie{Name: "guihong_session", Value: session.Token, Path: "/api", HttpOnly: true,
		SameSite: http.SameSiteStrictMode, MaxAge: 1800})
	writeAPI(writer, http.StatusOK, map[string]any{"user": user(session.Principal), "csrf": session.CSRF})
}

func identityError(writer http.ResponseWriter, err error) {
	switch {
	case errors.Is(err, application.ErrRateLimited):
		apiError(writer, http.StatusTooManyRequests, "RATE_LIMITED")
	case errors.Is(err, application.ErrAuthentication):
		apiError(writer, http.StatusUnauthorized, "AUTHENTICATION_FAILED")
	default:
		apiError(writer, http.StatusServiceUnavailable, "SERVICE_UNAVAILABLE")
	}
}

func decode(request *http.Request, value any) error {
	decoder := json.NewDecoder(io.LimitReader(request.Body, 1<<20))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(value); err != nil {
		return err
	}
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		return errors.New("multiple JSON values")
	}
	return nil
}

func writeAPI(writer http.ResponseWriter, status int, value any) {
	writer.Header().Set("Content-Type", "application/json;charset=UTF-8")
	writer.WriteHeader(status)
	_ = json.NewEncoder(writer).Encode(value)
}

func apiError(writer http.ResponseWriter, status int, code string) {
	writeAPI(writer, status, map[string]string{"code": code})
}
