package platform

import (
	"context"
	"database/sql"
	"fmt"
	"net"
	"sync/atomic"
	"time"

	"github.com/apache/rocketmq-client-go/v2/admin"
	"github.com/apache/rocketmq-client-go/v2/primitive"
	_ "github.com/go-sql-driver/mysql"
)

type Runtime struct {
	Config     Config
	Database   *sql.DB
	Witness    *Witness
	Store      *S3Client
	Objects    *ObjectRepository
	migrations []Migration
	draining   atomic.Bool
}

func NewRuntime(role string) (*Runtime, error) {
	config, err := LoadConfig(role)
	if err != nil {
		return nil, err
	}
	migrations, err := Migrations(role)
	if err != nil {
		return nil, err
	}
	database, err := sql.Open("mysql", config.DatabaseDSN)
	if err != nil {
		return nil, err
	}
	database.SetMaxOpenConns(8)
	database.SetMaxIdleConns(2)
	database.SetConnMaxLifetime(5 * time.Minute)
	store, err := NewS3Client(config.S3Endpoint, config.S3Bucket, config.S3Key, config.S3Secret)
	if err != nil {
		_ = database.Close()
		return nil, err
	}
	witness, err := NewWitness(database, config.WitnessRoot, role, config.SourceSHA, migrations)
	if err != nil {
		store.Close()
		_ = database.Close()
		return nil, err
	}
	runtime := &Runtime{Config: config, Database: database, Witness: witness, Store: store, migrations: migrations}
	runtime.Objects = NewObjectRepository(database, witness, store, runtime.Draining)
	reconcileContext, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	runtime.Objects.Reconcile(reconcileContext)
	return runtime, nil
}

func (runtime *Runtime) Close() error {
	runtime.Drain()
	runtime.Store.Close()
	witnessError := runtime.Witness.Close()
	databaseError := runtime.Database.Close()
	if witnessError != nil {
		return witnessError
	}
	return databaseError
}

func (runtime *Runtime) Drain() { runtime.draining.Store(true) }

func (runtime *Runtime) Draining() bool { return runtime.draining.Load() }

func (runtime *Runtime) Writable(ctx context.Context) bool {
	return !runtime.Draining() && runtime.Objects.Reconciled() && runtime.Witness.VerifyCurrent(ctx)
}

type Readiness struct {
	Service           string `json:"service"`
	State             string `json:"state"`
	Database          bool   `json:"database"`
	Storage           bool   `json:"storage"`
	MQ                bool   `json:"mq"`
	ObjectsReconciled bool   `json:"objects_reconciled"`
}

func (runtime *Runtime) Ready(parent context.Context) (Readiness, bool) {
	ctx, cancel := context.WithTimeout(parent, 10*time.Second)
	defer cancel()
	state, _ := runtime.Witness.State()
	if state == "WAITING_DEPENDENCY" {
		_ = runtime.Witness.Initialize(ctx, runtime.migrations)
	}
	databaseReady := runtime.Witness.VerifyCurrent(ctx)
	storageReady := runtime.Store.Ready(ctx)
	if databaseReady && storageReady && !runtime.Objects.Reconciled() {
		runtime.Objects.Reconcile(ctx)
	}
	objectsReady := runtime.Objects.Reconciled()
	mqReady := false
	if databaseReady && storageReady && objectsReady && !runtime.Draining() {
		mqReady = runtime.mqReady(ctx)
	}
	state, _ = runtime.Witness.State()
	if runtime.Draining() {
		state = "DRAINING"
	}
	result := Readiness{Service: runtime.Config.Role, State: state, Database: databaseReady,
		Storage: storageReady, MQ: mqReady, ObjectsReconciled: objectsReady}
	return result, databaseReady && storageReady && mqReady && objectsReady && !runtime.Draining()
}

func (runtime *Runtime) mqReady(parent context.Context) bool {
	ctx, cancel := context.WithTimeout(parent, 3*time.Second)
	defer cancel()
	api, err := admin.NewAdmin(admin.WithResolver(primitive.NewPassthroughResolver([]string{runtime.Config.NameServer})))
	if err != nil {
		return false
	}
	defer api.Close()
	if _, err := api.FetchAllTopicList(ctx); err != nil {
		return false
	}
	connection, err := net.DialTimeout("tcp", runtime.Config.Broker, time.Second)
	if err != nil {
		return false
	}
	_ = connection.Close()
	return true
}

func (runtime *Runtime) Identity() map[string]any {
	state, _ := runtime.Witness.State()
	return map[string]any{"service": runtime.Config.Role, "source_sha": runtime.Config.SourceSHA,
		"generation": runtime.Witness.Generation(), "state": state}
}

func (runtime *Runtime) RequireInternal(caller, authorization string) error {
	if caller != "lab" || len(authorization) < 8 || authorization[:7] != "Bearer " ||
		!Same(runtime.Config.InternalToken, authorization[7:]) {
		return fmt.Errorf("internal authentication required")
	}
	return nil
}
