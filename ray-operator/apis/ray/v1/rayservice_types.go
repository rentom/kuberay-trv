package v1

import (
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// EDIT THIS FILE!  THIS IS SCAFFOLDING FOR YOU TO OWN!
// NOTE: json tags are required.  Any new fields you add must have json tags for the fields to be serialized.

type ServiceStatus string

const (
	FailedToGetOrCreateRayCluster    ServiceStatus = "FailedToGetOrCreateRayCluster"
	WaitForServeDeploymentReady      ServiceStatus = "WaitForServeDeploymentReady"
	FailedToGetServeDeploymentStatus ServiceStatus = "FailedToGetServeDeploymentStatus"
	Running                          ServiceStatus = "Running"
	Restarting                       ServiceStatus = "Restarting"
	FailedToUpdateServingPodLabel    ServiceStatus = "FailedToUpdateServingPodLabel"
	FailedToUpdateService            ServiceStatus = "FailedToUpdateService"
)

// These statuses should match Ray Serve's application statuses
// See `enum ApplicationStatus` in https://sourcegraph.com/github.com/ray-project/ray/-/blob/src/ray/protobuf/serve.proto for more details.
var ApplicationStatusEnum = struct {
	NOT_STARTED   string
	DEPLOYING     string
	RUNNING       string
	DEPLOY_FAILED string
	DELETING      string
	UNHEALTHY     string
}{
	NOT_STARTED:   "NOT_STARTED",
	DEPLOYING:     "DEPLOYING",
	RUNNING:       "RUNNING",
	DEPLOY_FAILED: "DEPLOY_FAILED",
	DELETING:      "DELETING",
	UNHEALTHY:     "UNHEALTHY",
}

// These statuses should match Ray Serve's deployment statuses
var DeploymentStatusEnum = struct {
	UPDATING  string
	HEALTHY   string
	UNHEALTHY string
}{
	UPDATING:  "UPDATING",
	HEALTHY:   "HEALTHY",
	UNHEALTHY: "UNHEALTHY",
}

// RayServiceSpec defines the desired state of RayService
type RayServiceSpec struct {
	// Important: Run "make" to regenerate code after modifying this file
	// Defines the applications and deployments to deploy, should be a YAML multi-line scalar string.
	ServeConfigV2  string         `json:"serveConfigV2,omitempty"`
	RayClusterSpec RayClusterSpec `json:"rayClusterConfig,omitempty"`
	// Deprecated: This field is not used anymore. ref: https://github.com/ray-project/kuberay/issues/1685
	ServiceUnhealthySecondThreshold *int32 `json:"serviceUnhealthySecondThreshold,omitempty"`
	// Deprecated: This field is not used anymore. ref: https://github.com/ray-project/kuberay/issues/1685
	DeploymentUnhealthySecondThreshold *int32 `json:"deploymentUnhealthySecondThreshold,omitempty"`
	// ServeService is the Kubernetes service for head node and worker nodes who have healthy http proxy to serve traffics.
	ServeService *corev1.Service `json:"serveService,omitempty"`
}

// RayServiceStatuses defines the observed state of RayService
// +kubebuilder:printcolumn:name="ServiceStatus",type=string,JSONPath=".status.serviceStatus"
type RayServiceStatuses struct {
	ActiveServiceStatus RayServiceStatus `json:"activeServiceStatus,omitempty"`
	// Pending Service Status indicates a RayCluster will be created or is being created.
	PendingServiceStatus RayServiceStatus `json:"pendingServiceStatus,omitempty"`
	// ServiceStatus indicates the current RayService status.
	ServiceStatus ServiceStatus `json:"serviceStatus,omitempty"`
	// observedGeneration is the most recent generation observed for this RayService. It corresponds to the
	// RayService's generation, which is updated on mutation by the API Server.
	// +optional
	ObservedGeneration int64 `json:"observedGeneration,omitempty"`
	// LastUpdateTime represents the timestamp when the RayService status was last updated.
	LastUpdateTime *metav1.Time `json:"lastUpdateTime,omitempty"`
}

type RayServiceStatus struct {
	// Important: Run "make" to regenerate code after modifying this file
	Applications     map[string]AppStatus `json:"applicationStatuses,omitempty"`
	RayClusterName   string               `json:"rayClusterName,omitempty"`
	RayClusterStatus RayClusterStatus     `json:"rayClusterStatus,omitempty"`
}

type AppStatus struct {
	Status  string `json:"status,omitempty"`
	Message string `json:"message,omitempty"`
	// Keep track of how long the service is healthy.
	// Update when Serve deployment is healthy or first time convert to unhealthy from healthy.
	HealthLastUpdateTime *metav1.Time                     `json:"healthLastUpdateTime,omitempty"`
	Deployments          map[string]ServeDeploymentStatus `json:"serveDeploymentStatuses,omitempty"`
}

// ServeDeploymentStatus defines the current state of a Serve deployment
type ServeDeploymentStatus struct {
	// Name, Status, Message are from Ray Dashboard and represent a Serve deployment's state.
	// TODO: change status type to enum
	Status  string `json:"status,omitempty"`
	Message string `json:"message,omitempty"`
	// Keep track of how long the service is healthy.
	// Update when Serve deployment is healthy or first time convert to unhealthy from healthy.
	HealthLastUpdateTime *metav1.Time `json:"healthLastUpdateTime,omitempty"`
}

// +kubebuilder:object:root=true
// +kubebuilder:resource:categories=all
// +kubebuilder:subresource:status
// +kubebuilder:storageversion
// +genclient
// RayService is the Schema for the rayservices API
type RayService struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`

	Spec   RayServiceSpec     `json:"spec,omitempty"`
	Status RayServiceStatuses `json:"status,omitempty"`
}

//+kubebuilder:object:root=true

// RayServiceList contains a list of RayService
type RayServiceList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitempty"`
	Items           []RayService `json:"items"`
}

func init() {
	SchemeBuilder.Register(&RayService{}, &RayServiceList{})
}
