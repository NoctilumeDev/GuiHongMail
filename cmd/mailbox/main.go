package main

import (
	"log"
	"net/http"

	"github.com/NoctilumeDev/GuiHongMail/internal/mailbox/application"
	"github.com/NoctilumeDev/GuiHongMail/internal/mailbox/infrastructure"
	mailboxhttp "github.com/NoctilumeDev/GuiHongMail/internal/mailbox/interfaces"
	"github.com/NoctilumeDev/GuiHongMail/internal/platform"
)

func main() {
	log.SetFlags(log.Ldate | log.Ltime | log.LUTC)
	err := platform.RunService("mailbox", func(mux *http.ServeMux, runtime *platform.Runtime) {
		repository := infrastructure.NewIdentityRepository(runtime.Database, runtime.Witness, runtime.Writable)
		identity, err := application.NewIdentity(repository)
		if err != nil {
			panic(err)
		}
		mailboxhttp.Register(mux, runtime, identity)
		mailboxRepository := infrastructure.NewMailboxRepository(runtime.Database, runtime.Witness, runtime.Writable)
		mailbox := application.NewMailbox(mailboxRepository, infrastructure.MIMEParser{}, infrastructure.ConservativeHTML{}, runtime.Objects)
		mailboxhttp.RegisterMailbox(mux, runtime, identity, mailbox)
		mailboxhttp.RegisterWeb(mux, "backend/mailbox-service/src/main/resources/static")
	}, nil)
	if err != nil {
		log.Fatal(err)
	}
}
