package main

import (
	"log"
	"net/http"

	"github.com/NoctilumeDev/GuiHongMail/internal/ingress/infrastructure"
	"github.com/NoctilumeDev/GuiHongMail/internal/platform"
)

func main() {
	log.SetFlags(log.Ldate | log.Ltime | log.LUTC)
	if err := platform.RunService("ingress", func(mux *http.ServeMux, runtime *platform.Runtime) {
		infrastructure.RegisterIngress(mux, runtime)
	}, infrastructure.RunSMTP); err != nil {
		log.Fatal(err)
	}
}
