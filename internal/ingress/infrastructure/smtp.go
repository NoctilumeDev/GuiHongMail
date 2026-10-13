package infrastructure

import (
	"bufio"
	"context"
	"fmt"
	"io"
	"net"
	"net/textproto"
	"strings"
	"sync"
	"time"

	"github.com/NoctilumeDev/GuiHongMail/internal/platform"
)

const maxSMTPLine = 1000

func RunSMTP(ctx context.Context, runtime *platform.Runtime) error {
	return runSMTP(ctx, runtime.Config.SMTPAddress, runtime.Writable)
}

func runSMTP(ctx context.Context, address string, writable func(context.Context) bool) error {
	listener, err := net.Listen("tcp", address)
	if err != nil {
		return err
	}
	defer listener.Close()
	go func() {
		<-ctx.Done()
		_ = listener.Close()
	}()
	semaphore := make(chan struct{}, 2)
	var clients sync.WaitGroup
	defer clients.Wait()
	for {
		connection, err := listener.Accept()
		if err != nil {
			if ctx.Err() != nil {
				return nil
			}
			return err
		}
		select {
		case semaphore <- struct{}{}:
			clients.Add(1)
			go func() {
				defer clients.Done()
				defer func() { <-semaphore }()
				handleSMTP(ctx, writable, connection)
			}()
		default:
			_, _ = io.WriteString(connection, "421 Too many connections\r\n")
			_ = connection.Close()
		}
	}
}

func handleSMTP(ctx context.Context, writable func(context.Context) bool, connection net.Conn) {
	defer connection.Close()
	reader := textproto.NewReader(bufio.NewReaderSize(connection, 8*1024))
	writer := bufio.NewWriterSize(connection, 4*1024)
	reply := func(line string) bool {
		if _, err := writer.WriteString(line + "\r\n"); err != nil {
			return false
		}
		return writer.Flush() == nil
	}
	if !reply("220 guihong.test ESMTP GuiHong M1") {
		return
	}
	hello := false
	mailFrom := false
	for {
		if ctx.Err() != nil {
			return
		}
		_ = connection.SetDeadline(time.Now().Add(10 * time.Second))
		line, err := reader.ReadLine()
		if err != nil {
			return
		}
		if len(line) > maxSMTPLine {
			reply("500 Line too long")
			return
		}
		command, argument := splitSMTP(line)
		switch command {
		case "EHLO":
			hello, mailFrom = argument != "", false
			if !hello {
				reply("501 Domain required")
				continue
			}
			if _, err := writer.WriteString("250-guihong.test\r\n250-SIZE 5242880\r\n250 HELP\r\n"); err != nil || writer.Flush() != nil {
				return
			}
		case "HELO":
			hello, mailFrom = argument != "", false
			if !hello {
				reply("501 Domain required")
			} else {
				reply("250 guihong.test")
			}
		case "MAIL":
			if !hello {
				reply("503 Send HELO/EHLO first")
				continue
			}
			if !strings.HasPrefix(strings.ToUpper(argument), "FROM:") {
				reply("501 MAIL FROM required")
				continue
			}
			if !writable(ctx) {
				reply("451 Service temporarily unavailable")
				continue
			}
			mailFrom = true
			reply("250 Sender accepted")
		case "RCPT":
			if !mailFrom {
				reply("503 MAIL FROM required")
				continue
			}
			address, valid := smtpRecipient(argument)
			if !valid {
				reply("501 RCPT TO required")
				continue
			}
			at := strings.LastIndex(address, "@")
			if at < 1 || !strings.EqualFold(address[at+1:], "guihong.test") {
				reply("550 Relay denied")
				continue
			}
			reply("451 Durable local reception not available in M1")
		case "DATA":
			reply("503 No accepted recipient or durable responsibility")
		case "RSET":
			mailFrom = false
			reply("250 Reset")
		case "NOOP":
			reply("250 OK")
		case "QUIT":
			reply("221 Bye")
			return
		default:
			reply("500 Command unrecognized")
		}
	}
}

func splitSMTP(line string) (string, string) {
	line = strings.TrimSpace(line)
	if line == "" {
		return "", ""
	}
	parts := strings.SplitN(line, " ", 2)
	if len(parts) == 1 {
		return strings.ToUpper(parts[0]), ""
	}
	return strings.ToUpper(parts[0]), strings.TrimSpace(parts[1])
}

func smtpRecipient(argument string) (string, bool) {
	if !strings.HasPrefix(strings.ToUpper(argument), "TO:") {
		return "", false
	}
	value := strings.TrimSpace(argument[3:])
	if !strings.HasPrefix(value, "<") {
		return "", false
	}
	end := strings.Index(value, ">")
	if end < 2 || strings.TrimSpace(value[end+1:]) != "" {
		return "", false
	}
	address := value[1:end]
	if strings.ContainsAny(address, "<>\r\n ") {
		return "", false
	}
	return address, true
}

func SMTPAddress(runtime *platform.Runtime) string {
	return fmt.Sprintf("smtp://%s", runtime.Config.SMTPAddress)
}
