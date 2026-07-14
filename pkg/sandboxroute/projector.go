/*
Copyright 2026.

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

package sandboxroute

import (
	"errors"
	"reflect"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// Resolver returns the opaque sandbox ID for an object.
type Resolver func(metav1.Object) string

// ProjectionInput contains neutral object metadata and routing data.
type ProjectionInput struct {
	Object             metav1.Object
	IP                 string
	State              string
	Owner              string
	AccessToken        string
	RequireTrafficAuth bool
}

// Projector constructs Routes using an injected ID resolver.
type Projector struct {
	resolver Resolver
}

// NewProjector creates a Projector with the supplied resolver.
func NewProjector(resolver Resolver) *Projector {
	return &Projector{resolver: resolver}
}

// Project constructs a Route without applying Sandbox ID policy.
func (p *Projector) Project(input ProjectionInput) (Route, error) {
	if isNilObject(input.Object) {
		return Route{}, errors.New("project route: object is nil")
	}
	if p == nil || p.resolver == nil {
		return Route{}, errors.New("project route: resolver is nil")
	}

	id := p.resolver(input.Object)
	if id == "" {
		return Route{}, errors.New("project route: resolver returned an empty sandbox ID")
	}

	return Route{
		IP:                 input.IP,
		ID:                 id,
		Namespace:          input.Object.GetNamespace(),
		Name:               input.Object.GetName(),
		UID:                input.Object.GetUID(),
		Owner:              input.Owner,
		State:              input.State,
		ResourceVersion:    input.Object.GetResourceVersion(),
		AccessToken:        input.AccessToken,
		RequireTrafficAuth: input.RequireTrafficAuth,
	}, nil
}

func isNilObject(object metav1.Object) bool {
	if object == nil {
		return true
	}
	value := reflect.ValueOf(object)
	switch value.Kind() {
	case reflect.Chan, reflect.Func, reflect.Interface, reflect.Map, reflect.Pointer, reflect.Slice:
		return value.IsNil()
	default:
		return false
	}
}
