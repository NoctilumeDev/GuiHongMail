package main

import (
	"log"

	"github.com/NoctilumeDev/GuiHongMail/internal/platform"
)

func main() {
	log.SetFlags(log.Ldate | log.Ltime | log.LUTC)
	if err := platform.RunService("delivery", nil, nil); err != nil {
		log.Fatal(err)
	}
}
