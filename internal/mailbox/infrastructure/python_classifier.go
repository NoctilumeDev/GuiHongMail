package infrastructure

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"os"
	"os/exec"
	"time"

	"github.com/NoctilumeDev/GuiHongMail/internal/mailbox/application"
	"github.com/NoctilumeDev/GuiHongMail/internal/mailbox/domain"
)

const classifierContract = "guihong-classifier/1"
const classifierAlgorithm = "multinomial-nb/1"

type PythonClassifier struct {
	executable string
	script     string
}

func NewPythonClassifier(executable, script string) *PythonClassifier {
	return &PythonClassifier{executable: executable, script: script}
}

func (p *PythonClassifier) Predict(ctx context.Context, samples []domain.TrainingSample, features []string) (domain.ModelPrediction, error) {
	request := struct {
		Contract  string                  `json:"contract"`
		Algorithm string                  `json:"algorithm"`
		Samples   []domain.TrainingSample `json:"samples"`
		Query     struct {
			Features []string `json:"features"`
		} `json:"query"`
	}{Contract: classifierContract, Algorithm: classifierAlgorithm, Samples: samples}
	request.Query.Features = features
	payload, err := json.Marshal(request)
	if err != nil || len(payload) > 1024*1024 {
		return domain.ModelPrediction{}, fmt.Errorf("classification request exceeds contract")
	}
	callContext, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()
	command := exec.CommandContext(callContext, p.executable, "-I", p.script)
	command.Env = []string{"PYTHONIOENCODING=utf-8", "PYTHONUTF8=1"}
	for _, name := range []string{"SystemRoot", "WINDIR"} {
		if value := os.Getenv(name); value != "" {
			command.Env = append(command.Env, name+"="+value)
		}
	}
	command.Stdin = bytes.NewReader(payload)
	stdout := &limitBuffer{limit: 1024 * 1024}
	stderr := &limitBuffer{limit: 16 * 1024}
	command.Stdout, command.Stderr = stdout, stderr
	if err := command.Run(); err != nil {
		if errors.Is(callContext.Err(), context.DeadlineExceeded) {
			return domain.ModelPrediction{}, fmt.Errorf("classification algorithm timeout")
		}
		return domain.ModelPrediction{}, fmt.Errorf("classification algorithm failed: %w", err)
	}
	var response struct {
		Contract  string `json:"contract"`
		Algorithm string `json:"algorithm"`
		domain.ModelPrediction
	}
	if err := json.Unmarshal(stdout.Bytes(), &response); err != nil || response.Contract != classifierContract || response.Algorithm != classifierAlgorithm {
		return domain.ModelPrediction{}, fmt.Errorf("classification algorithm returned invalid contract")
	}
	value := response.ModelPrediction
	if value.Status == "PREDICTED" {
		if value.CategoryID == nil || value.ModelVersion == "" || value.SampleDigest == "" || value.SampleCount != len(samples) || math.IsNaN(value.Confidence) || math.IsInf(value.Confidence, 0) || math.IsNaN(value.Margin) || math.IsInf(value.Margin, 0) || value.Confidence < 0 || value.Confidence > 1 || value.Margin < 0 || value.Margin > 1 {
			return domain.ModelPrediction{}, fmt.Errorf("classification prediction exceeded output contract")
		}
	} else {
		switch value.Status {
		case "COLD_START", "EMPTY_FEATURES":
		default:
			return domain.ModelPrediction{}, fmt.Errorf("classification status is not supported")
		}
	}
	return value, nil
}

type limitBuffer struct {
	data  bytes.Buffer
	limit int
}

func (b *limitBuffer) Write(value []byte) (int, error) {
	if b.data.Len()+len(value) > b.limit {
		return 0, io.ErrShortBuffer
	}
	return b.data.Write(value)
}

func (b *limitBuffer) Bytes() []byte { return b.data.Bytes() }

var _ application.ClassificationAlgorithm = (*PythonClassifier)(nil)
