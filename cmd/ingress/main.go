package main

import (
	"log"

	"github.com/NoctilumeDev/GuiHongMail/internal/ingress/infrastructure"
	"github.com/NoctilumeDev/GuiHongMail/internal/platform"
)

func main() {
	log.SetFlags(log.Ldate | log.Ltime | log.LUTC)
	if err := platform.RunService("ingress", nil, infrastructure.RunSMTP); err != nil {
		log.Fatal(err)
	}
}
