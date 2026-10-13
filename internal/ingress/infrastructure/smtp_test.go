package infrastructure

import (
	"bufio"
	"context"
	"net"
	"strings"
	"testing"
	"time"
)

func TestSMTPRejectsRelayAndUnimplementedLocalResponsibility(t *testing.T) {
	server, client := net.Pipe()
	defer client.Close()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go handleSMTP(ctx, func(context.Context) bool { return true }, server)
	reader := bufio.NewReader(client)
	readPrefix(t, reader, "220 ")
	writeLine(t, client, "EHLO test")
	readPrefix(t, reader, "250-")
	readPrefix(t, reader, "250-")
	readPrefix(t, reader, "250 ")
	writeLine(t, client, "MAIL FROM:<sender@example.test>")
	readPrefix(t, reader, "250 ")
	writeLine(t, client, "RCPT TO:<victim@example.net>")
	readPrefix(t, reader, "550 ")
	writeLine(t, client, "RCPT TO:<alice@guihong.test>")
	readPrefix(t, reader, "451 ")
	writeLine(t, client, "DATA")
	readPrefix(t, reader, "503 ")
	writeLine(t, client, "QUIT")
	readPrefix(t, reader, "221 ")
}

func TestSMTPRefusesMailWhenRuntimeIsNotWritable(t *testing.T) {
	server, client := net.Pipe()
	defer client.Close()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go handleSMTP(ctx, func(context.Context) bool { return false }, server)
	reader := bufio.NewReader(client)
	readPrefix(t, reader, "220 ")
	writeLine(t, client, "HELO test")
	readPrefix(t, reader, "250 ")
	writeLine(t, client, "MAIL FROM:<sender@example.test>")
	readPrefix(t, reader, "451 ")
}

func writeLine(t *testing.T, connection net.Conn, line string) {
	t.Helper()
	_ = connection.SetDeadline(time.Now().Add(time.Second))
	if _, err := connection.Write([]byte(line + "\r\n")); err != nil {
		t.Fatal(err)
	}
}

func readPrefix(t *testing.T, reader *bufio.Reader, prefix string) {
	t.Helper()
	line, err := reader.ReadString('\n')
	if err != nil {
		t.Fatal(err)
	}
	if !strings.HasPrefix(line, prefix) {
		t.Fatalf("reply %q does not start with %q", line, prefix)
	}
}
