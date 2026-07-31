/*
Copyright 2025.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

package runtime

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"sync"
	"time"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/klog/v2"
	"sigs.k8s.io/controller-runtime/pkg/client"

	agentsv1alpha1 "github.com/openkruise/agents/api/v1alpha1"
	"github.com/openkruise/agents/pkg/agent-runtime/storages"
	"github.com/openkruise/agents/pkg/cache"
	"github.com/openkruise/agents/pkg/utils"
	csimountutils "github.com/openkruise/agents/pkg/utils/csiutils"
	"github.com/openkruise/agents/pkg/utils/logs"
	"github.com/openkruise/agents/pkg/utils/runtime/config"
	"github.com/openkruise/agents/proto/envd/process"
)

var MountCommand = "/mnt/envd/sandbox-runtime-storage"

// CSIMount creates a dynamic mount point in Sandbox with `sandbox-storage` cli.
// It accepts the raw Sandbox API object to avoid circular dependency on the sandboxcr package.
//
// NOTE: `sandbox-storage` cli should be injected with `sandbox-runtime` and will be replaced by a built-in service of
// `sandbox-runtime`.
func CSIMount(ctx context.Context, sbx *agentsv1alpha1.Sandbox, driver string, request string) error {
	log := klog.FromContext(ctx).WithValues("sandbox", klog.KObj(sbx))
	startTime := time.Now()
	processConfig := &process.ProcessConfig{
		Cmd: MountCommand,
		Args: []string{
			"mount",
			"--driver", driver,
			"--config", request,
		},
		Cwd: nil,
		Envs: map[string]string{
			"POD_UID": string(sbx.Status.PodInfo.PodUID),
		},
	}

	result, err := RunCommandWithRuntime(ctx, RunCmdFuncArgs{
		Sbx:           sbx,
		ProcessConfig: processConfig,
		Timeout:       30 * time.Second,
		// The mount CLI manipulates mounts inside the sandbox and must run as root.
		AuthUser: "root",
	})
	if err != nil {
		log.Error(err, "failed to run command", "stdout", result.Stdout, "stderr", result.Stderr)
		return err
	}
	if result.ExitCode != 0 {
		err = fmt.Errorf("command failed: [%d] %s", result.ExitCode, result.Stderr)
		log.Error(err, "command failed", "exitCode", result.ExitCode)
		return err
	}
	log.Info("execute csi mount command", "driverName", driver, "mountCost", time.Since(startTime))
	return nil
}

// ProcessCSIMounts performs CSI volume mounting operations for all mount configurations concurrently.
// It uses opts.Concurrency to limit the number of concurrent mount goroutines.
// If Concurrency is 0 or negative, it defaults to config.DefaultCSIMountConcurrency.
// Returns the total duration spent on all mount operations and all encountered errors (joined via errors.Join).
func ProcessCSIMounts(ctx context.Context, sbx *agentsv1alpha1.Sandbox, opts config.CSIMountOptions) (time.Duration, error) {
	log := klog.FromContext(ctx).WithValues("sandbox", klog.KObj(sbx))
	start := time.Now()

	var wg sync.WaitGroup
	errCh := make(chan error, len(opts.MountOptionList))

	// Use a semaphore channel to limit concurrency
	concurrency := opts.Concurrency
	if concurrency <= 0 {
		concurrency = config.DefaultCSIMountConcurrency
	}
	sem := make(chan struct{}, concurrency)

	for _, opt := range opts.MountOptionList {
		wg.Add(1)
		sem <- struct{}{}
		go func(opt config.MountConfig) {
			defer wg.Done()
			defer func() { <-sem }()
			mountDuration, err := doCSIMount(ctx, sbx, opt)
			if err != nil {
				log.Error(err, "failed to perform CSI mount", "mountOptionConfig", opt)
				errCh <- err
				return
			}
			log.Info("CSI mount completed successfully",
				"mountOptionConfig", opt,
				"duration", mountDuration)
		}(opt)
	}

	wg.Wait()
	close(errCh)

	var errs []error
	for err := range errCh {
		errs = append(errs, err)
	}
	return time.Since(start), errors.Join(errs...)
}

func doCSIMount(ctx context.Context, sbx *agentsv1alpha1.Sandbox, opts config.MountConfig) (time.Duration, error) {
	ctx = logs.Extend(ctx, "action", "csiMount")
	start := time.Now()
	err := CSIMount(ctx, sbx, opts.Driver, opts.RequestRaw)
	return time.Since(start), err
}

// GetCsiMountExtensionRequest parses the CSI mount extension request from object annotations.
func GetCsiMountExtensionRequest(s metav1.Object) ([]agentsv1alpha1.CSIMountConfig, error) {
	var csiMountRequests []agentsv1alpha1.CSIMountConfig
	csiMountRequestsRaw := s.GetAnnotations()[agentsv1alpha1.AnnotationCSIVolumeConfig]
	if csiMountRequestsRaw == "" {
		return nil, nil
	}
	if err := json.Unmarshal([]byte(csiMountRequestsRaw), &csiMountRequests); err != nil {
		return nil, fmt.Errorf("failed to unmarshal csi mount options: %v", err)
	}
	return csiMountRequests, nil
}

// ResolveCSIMountFromAnnotation parses CSI mount config from sandbox annotation and resolves it into MountOptionList.
// Returns nil if no CSI mount annotation is present.
func ResolveCSIMountFromAnnotation(ctx context.Context, obj metav1.Object, client client.Client, cache cache.Provider, storageRegistry storages.VolumeMountProviderRegistry) (*config.CSIMountOptions, error) {
	log := klog.FromContext(ctx)
	csiMountConfigs, err := GetCsiMountExtensionRequest(obj)
	if err != nil {
		log.Error(err, "failed to parse csi mount config from annotation")
		return nil, fmt.Errorf("failed to parse csi mount config from annotation: %w", err)
	}
	if len(csiMountConfigs) == 0 {
		return nil, nil
	}
	csiClient := csimountutils.NewCSIMountHandler(cache.GetClient(), cache.GetAPIReader(), storageRegistry, utils.DefaultSandboxDeployNamespace)
	mountOptionList := make([]config.MountConfig, 0, len(csiMountConfigs))
	for _, cfg := range csiMountConfigs {
		driverName, csiReqConfigRaw, genErr := csiClient.CSIMountOptionsConfig(ctx, cfg)
		if genErr != nil {
			log.Error(genErr, "failed to generate csi mount options config", "mountConfig", cfg)
			return nil, fmt.Errorf("failed to generate csi mount options config: %w", genErr)
		}
		mountOptionList = append(mountOptionList, config.MountConfig{Driver: driverName, RequestRaw: csiReqConfigRaw})
	}
	return &config.CSIMountOptions{MountOptionList: mountOptionList}, nil
}
