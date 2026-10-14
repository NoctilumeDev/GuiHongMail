package main

import (
	"context"
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
		sender := application.NewSender(mailboxRepository, mailboxRepository, infrastructure.MIMEParser{}, runtime.Objects)
		mailboxhttp.RegisterSend(mux, runtime, identity, sender, mailboxRepository)
		classifier := application.NewClassifier(mailboxRepository, infrastructure.NewPythonClassifier(runtime.Config.ClassifierPython, runtime.Config.ClassifierScript))
		mailboxhttp.RegisterClassification(mux, identity, classifier)
		mailboxhttp.RegisterWeb(mux, "backend/mailbox-service/src/main/resources/static")
	}, func(ctx context.Context, runtime *platform.Runtime) error {
		mailboxRepository := infrastructure.NewMailboxRepository(runtime.Database, runtime.Witness, runtime.Writable)
		sender := application.NewSender(mailboxRepository, mailboxRepository, infrastructure.MIMEParser{}, runtime.Objects)
		importer := application.NewIngressImporter(mailboxRepository, infrastructure.MIMEParser{}, runtime.Objects)
		classifier := application.NewClassifier(mailboxRepository, infrastructure.NewPythonClassifier(runtime.Config.ClassifierPython, runtime.Config.ClassifierScript))
		errorsChannel := make(chan error, 2)
		go func() { errorsChannel <- sender.Run(ctx, runtime, importer) }()
		go func() { errorsChannel <- classifier.Run(ctx) }()
		select {
		case <-ctx.Done():
			return nil
		case failure := <-errorsChannel:
			return failure
		}
	})
	if err != nil {
		log.Fatal(err)
	}
}
