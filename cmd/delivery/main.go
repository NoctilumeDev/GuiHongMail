package main

import (
	"log"
	"net/http"

	"github.com/NoctilumeDev/GuiHongMail/internal/delivery/infrastructure"
	"github.com/NoctilumeDev/GuiHongMail/internal/platform"
)

func main() {
	log.SetFlags(log.Ldate | log.Ltime | log.LUTC)
	if err := platform.RunService("delivery", func(mux *http.ServeMux, runtime *platform.Runtime) {
		infrastructure.Register(mux, runtime)
	}, infrastructure.Run); err != nil {
		log.Fatal(err)
	}
}
