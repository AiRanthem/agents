FROM golang:1.25 AS builder

WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY api ./api
COPY client ./client
COPY proto ./proto
COPY pkg ./pkg
COPY test/e2b/assets/peer-mtls/helper ./test/e2b/assets/peer-mtls/helper
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /peer-mtls-helper ./test/e2b/assets/peer-mtls/helper

FROM scratch
COPY --from=builder /peer-mtls-helper /peer-mtls-helper
USER 65532:65532
ENTRYPOINT ["/peer-mtls-helper"]
