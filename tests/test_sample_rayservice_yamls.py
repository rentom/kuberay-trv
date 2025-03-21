''' Test sample RayService YAML files to catch invalid and outdated ones. '''
from copy import deepcopy
from kubernetes import client
import logging
import pytest
import sys
from tempfile import NamedTemporaryFile
import time
from typing import Any, Dict, List, Optional
import yaml

from framework.prototype import (
    RuleSet,
    CREvent,
    EasyJobRule,
    CurlServiceRule,
    AutoscaleRule,
    get_expected_head_pods,
    get_expected_worker_pods,
    show_cluster_info,
    check_pod_running,
)

from framework.utils import (
    start_curl_pod,
    logger,
    shell_subprocess_run,
    CONST,
    K8S_CLUSTER_MANAGER,
    OperatorManager
)

logger = logging.getLogger(__name__)

NAMESPACE = 'default'

class RayServiceAddCREvent(CREvent):
    """CREvent for RayService addition"""

    def exec(self):
        shell_subprocess_run(f"kubectl apply -n {self.namespace} -f {self.filepath}")

    def wait(self):
        """Wait for RayService to converge

        Wait until:
          (1) The number of head pods and worker pods are as expected.
          (2) All head pods and worker pods are "Running".
          (3) Service named "rayservice-sample-serve" presents
        """

        logger.info("Waiting for pods in ray service to be running...")
        k8s_v1_api = K8S_CLUSTER_MANAGER.k8s_client_dict[CONST.K8S_V1_CLIENT_KEY]

        start_time = time.time()
        expected_head_pods = get_expected_head_pods(self.custom_resource_object)
        expected_worker_pods = get_expected_worker_pods(self.custom_resource_object)
        while time.time() - start_time < self.timeout:
            headpods = k8s_v1_api.list_namespaced_pod(
                namespace = self.namespace, label_selector='ray.io/node-type=head')
            workerpods = k8s_v1_api.list_namespaced_pod(
                namespace = self.namespace, label_selector='ray.io/node-type=worker')
            serve_services = k8s_v1_api.list_namespaced_service(
                namespace = self.namespace, label_selector =
                f"ray.io/originated-from-cr-name={self.custom_resource_object['metadata']['name']},"
                f"ray.io/originated-from-crd=RayService,"
                f"ray.io/serve={self.custom_resource_object['metadata']['name']}-serve")

            logger.info(
                "Number of head Pods: %d, Number of worker Pods: %d, Number of serve services: %d",
                len(headpods.items), len(workerpods.items), len(serve_services.items)
            )

            if (len(serve_services.items) == 1 and len(headpods.items) == expected_head_pods
                    and len(workerpods.items) == expected_worker_pods
                    and check_pod_running(headpods.items) and check_pod_running(workerpods.items)):
                logger.info("--- RayServiceAddCREvent %s seconds ---", time.time() - start_time)
                return

            time.sleep(1)

        logger.info(f"RayServiceAddCREvent wait() failed to converge in {self.timeout}s.")
        logger.info(
            f"expected_head_pods: {expected_head_pods}, "
            f"expected_worker_pods: {expected_worker_pods}"
        )
        show_cluster_info(self.namespace)
        raise TimeoutError(f"RayServiceAddCREvent didn't finish in {self.timeout}s")

class RayServiceUpdateCREvent(CREvent):
    """CREvent for RayService update"""

    def __init__(
        self,
        custom_resource_object,
        rulesets: List[RuleSet] = [],
        timeout: int = 90,
        namespace: str = "default",
        filepath: Optional[str] = None,
        switch_cluster: bool = False,
        query_while_updating: Optional[Dict[str, str]] = None,
    ):
        super().__init__(custom_resource_object, rulesets, timeout, namespace, filepath)
        self.name = self.custom_resource_object["metadata"]["name"]
        self.query_rule = None
        self.switch_cluster = switch_cluster
        if query_while_updating:
            self.query_rule = CurlServiceRule(queries=query_while_updating)

    def get_ray_service_info(self):
        k8s_cr_api: client.CustomObjectsApi = K8S_CLUSTER_MANAGER.k8s_client_dict[CONST.K8S_CR_CLIENT_KEY]
        return k8s_cr_api.get_namespaced_custom_object_status(
            group="ray.io",
            namespace=self.namespace,
            name=self.name,
            version="v1",
            plural="rayservices",
        )

    def get_active_ray_cluster_name(self):
        rayservice_info = self.get_ray_service_info()
        return rayservice_info["status"]["activeServiceStatus"]["rayClusterName"]

    def exec(self):
        """Update a CR by a `kubectl apply` command."""
        self.old_cluster_name = self.get_active_ray_cluster_name()

        self.start = time.time()
        shell_subprocess_run(f"kubectl apply -n {self.namespace} -f {self.filepath}")

    def wait_for_status(self, status: str):
        """Helper function to check for service status."""

        while time.time() - self.start < self.timeout:
            rayservice_info = self.get_ray_service_info()
            if rayservice_info["status"]["serviceStatus"] == status:
                break

            if self.query_rule:
                self.query_rule.assert_rule(self.custom_resource_object, self.namespace)

            time.sleep(0.1)
        else:
            raise TimeoutError(
                f'Ray service "{self.name}" did not transition to status "{status}" '
                f"after {self.timeout}s."
            )

    def wait(self):
        """Wait for deployment to transition -> WaitForServeDeploymentReady -> Running"""

        self.wait_for_status("WaitForServeDeploymentReady")
        logger.info("Ray service transitioned to status WaitForServeDeploymentReady.")
        self.wait_for_status("Running")
        logger.info("Ray service transitioned to status Running.")

        if self.switch_cluster:
            current_cluster_name = self.get_active_ray_cluster_name()
            assert current_cluster_name != self.old_cluster_name
            logger.info(f'Ray service has moved to cluster "{current_cluster_name}"')

            # Wait 20 seconds for the serve service to update.
            # TODO (Yicheng-Lu-llll): This workaround should be removed after
            # refactoring the way of rolling out and redefining service status.
            # Currently, changing to 'running' status does not guarantee that
            # the serve service will redirect traffic to the new Raycluster.
            time.sleep(20)

class RayServiceDeleteCREvent(CREvent):
    """CREvent for RayService deletion"""
    def exec(self):
        """Delete a CR by a `kubectl delete` command."""
        shell_subprocess_run(f"kubectl delete -n {self.namespace} -f {self.filepath}")

    def wait(self):
        """Wait for pods to be deleted"""
        k8s_v1_api = K8S_CLUSTER_MANAGER.k8s_client_dict[CONST.K8S_V1_CLIENT_KEY]
        start_time = time.time()
        while time.time() - start_time < self.timeout:
            headpods = k8s_v1_api.list_namespaced_pod(
                namespace = self.namespace, label_selector = 'ray.io/node-type=head')
            workerpods = k8s_v1_api.list_namespaced_pod(
                namespace = self.namespace, label_selector = 'ray.io/node-type=worker')
            if (len(headpods.items) == 0 and len(workerpods.items) == 0):
                logger.info("--- Cleanup RayService %s seconds ---", time.time() - start_time)
                return
            time.sleep(1)

        logger.info(f"RayServiceDeleteCREvent failed to converge in {self.timeout}s.")
        logger.info("expected_head_pods: 0, expected_worker_pods: 0")
        show_cluster_info(self.namespace)
        raise TimeoutError(f"RayServiceDeleteCREvent didn't finish in {self.timeout}s.")


class TestRayService:
    sample_path = CONST.REPO_ROOT.joinpath("ray-operator/config/samples/").joinpath('ray-service.sample.yaml')

    @pytest.fixture
    def set_up_cluster(self):
        with open(self.sample_path, encoding="utf-8") as cr_yaml:
            self.cr = yaml.safe_load(cr_yaml)

        self.default_queries = [
            {"path": "/fruit", "json_args": ["MANGO", 2], "expected_output": "6"},
            {"path": "/calc", "json_args": ["MUL", 3], "expected_output": "15 pizzas please!"},
        ]

        K8S_CLUSTER_MANAGER.cleanup()
        K8S_CLUSTER_MANAGER.initialize_cluster()
        operator_manager = OperatorManager.instance()
        operator_manager.prepare_operator()
        start_curl_pod("curl", "default")

        yield

        K8S_CLUSTER_MANAGER.cleanup()

    def test_deploy_applications(self, set_up_cluster):
        rs = RuleSet([EasyJobRule(), CurlServiceRule(queries=self.default_queries)])
        cr_events: List[CREvent] = [
            RayServiceAddCREvent(self.cr, [rs], 90, NAMESPACE, self.sample_path),
            RayServiceDeleteCREvent(self.cr, [], 90, NAMESPACE, self.sample_path)
        ]

        for cr_event in cr_events:
            cr_event.trigger()

    def test_in_place_update(self, set_up_cluster):
        # Modify the MangoStand price and Multiplier factor
        updated_cr = deepcopy(self.cr)
        config = yaml.safe_load(self.cr["spec"]["serveConfigV2"])
        config["applications"][0]["deployments"][0]["user_config"]["price"] = 4
        config["applications"][1]["deployments"][1]["user_config"]["factor"] = 3
        updated_cr["spec"]["serveConfigV2"] = yaml.safe_dump(config)

        updated_queries = [
            {"path": "/fruit", "json_args": ["MANGO", 2], "expected_output": "8"},
            {"path": "/calc", "json_args": ["MUL", 3], "expected_output": "9 pizzas please!"},
        ]

        with NamedTemporaryFile(mode="w+", suffix=".yaml") as yaml_copy:
            logger.info(f"Writing modified RayService yaml to {yaml_copy.name}.")
            yaml_copy.writelines(yaml.safe_dump(updated_cr))
            yaml_copy.flush()

            cr_events: List[CREvent] = [
                RayServiceAddCREvent(
                    custom_resource_object=self.cr,
                    rulesets=[RuleSet([EasyJobRule(), CurlServiceRule(queries=self.default_queries)])],
                    timeout=90,
                    namespace=NAMESPACE,
                    filepath=self.sample_path
                ),
                RayServiceUpdateCREvent(
                    custom_resource_object=self.cr,
                    rulesets=[RuleSet([EasyJobRule(), CurlServiceRule(queries=updated_queries)])],
                    timeout=90,
                    namespace=NAMESPACE,
                    filepath=yaml_copy.name
                ),
                RayServiceDeleteCREvent(self.cr, [], 90, NAMESPACE, self.sample_path),
            ]

            for cr_event in cr_events:
                cr_event.trigger()

    def test_zero_downtime_rollout(self, set_up_cluster):
        # Modify the cluster spec to trigger a rollout
        updated_cr = deepcopy(self.cr)

        config = yaml.safe_load(self.cr["spec"]["serveConfigV2"])
        config["applications"][0]["deployments"][0]["user_config"]["price"] = 4
        config["applications"][1]["deployments"][1]["user_config"]["factor"] = 3
        updated_cr["spec"]["serveConfigV2"] = yaml.safe_dump(config)

        env = [{"name": "SAMPLE_ENV_VAR", "value": "SAMPLE_VALUE"}]
        updated_cr["spec"]["rayClusterConfig"]["headGroupSpec"]["template"]["spec"]["containers"][0]["env"] = env

        updated_queries = [
            {"path": "/fruit", "json_args": ["MANGO", 2], "expected_output": "8"},
            {"path": "/calc", "json_args": ["MUL", 3], "expected_output": "9 pizzas please!"},
        ]
        allowed_queries_during_update = deepcopy(self.default_queries)
        allowed_queries_during_update[0]["expected_output"] = {"6", "8"}
        allowed_queries_during_update[1]["expected_output"] = {"15 pizzas please!", "9 pizzas please!"}

        with NamedTemporaryFile(mode="w+", suffix=".yaml") as yaml_copy:
            logger.info(f"Writing modified RayService yaml to {yaml_copy.name}.")
            yaml_copy.writelines(yaml.safe_dump(updated_cr))
            yaml_copy.flush()

            cr_events: List[CREvent] = [
                RayServiceAddCREvent(
                    custom_resource_object=self.cr,
                    rulesets=[RuleSet([EasyJobRule(), CurlServiceRule(queries=self.default_queries)])],
                    filepath=self.sample_path
                ),
                RayServiceUpdateCREvent(
                    custom_resource_object=self.cr,
                    rulesets=[RuleSet([CurlServiceRule(queries=updated_queries)])],
                    filepath=yaml_copy.name,
                    switch_cluster=True,
                    query_while_updating=allowed_queries_during_update,
                ),
                RayServiceDeleteCREvent(custom_resource_object=self.cr, filepath=self.sample_path),
            ]

            for cr_event in cr_events:
                cr_event.trigger()

class TestRayServiceAutoscaling:
    """Test RayService autoscaling"""
    @pytest.fixture
    def set_up_cluster(self):
        """Set up a K8s cluster, deploy the KubeRay operator, and start a curl Pod"""
        K8S_CLUSTER_MANAGER.cleanup()
        K8S_CLUSTER_MANAGER.initialize_cluster()
        operator_manager = OperatorManager.instance()
        operator_manager.prepare_operator()
        start_curl_pod("curl", "default")

        yield

        K8S_CLUSTER_MANAGER.cleanup()

    def test_service_autoscaling(self, set_up_cluster):
        """This test uses a special workload that can allow us to
        reliably test autoscaling.

        The workload consists of two applications. The first application
        checks on an event in the second application. If the event isn't
        set, the first application will block on requests until the
        event is set. So, first we send a bunch of requests to the first
        application, which will trigger Serve autoscaling to bring up
        more replicas since the existing replicas are blocked on
        requests. Worker pods should scale up. Then we set the event in
        the second application, releasing all blocked requests. Worker
        pods should scale down.

        TODO (kevin85421): Currently, we configure the RayService YAML to
        ensure each Pod has at least 1 Ray Serve replica. Hence, all Pods
        can pass the readiness check and become ready. Without this workaround,
        the RayServiceAddCREvent will fail to converge.
        """
        dir_path = "ray-operator/config/samples/"
        cr_yaml_path = CONST.REPO_ROOT.joinpath(dir_path).joinpath("ray-service.autoscaler.yaml")
        with open(cr_yaml_path, encoding="utf-8") as cr_yaml:
            cr = yaml.safe_load(cr_yaml)

        scale_up_rule = AutoscaleRule(
            query={"path": "/", "json_args": {}},
            num_repeat=20,
            expected_worker_pods=5,
            timeout=30,
            message="Sending a lot of requests. Worker pods should start scaling up..."
        )
        scale_down_rule = AutoscaleRule(
            query={"path": "/signal", "json_args": {}},
            num_repeat=1,
            expected_worker_pods=0,
            timeout=400,
            message="Releasing all blocked requests. Worker pods should start scaling down..."
        )
        cr_events: List[CREvent] = [
            RayServiceAddCREvent(
                custom_resource_object=cr,
                rulesets=[RuleSet([scale_up_rule, scale_down_rule])],
                timeout=120,
                namespace=NAMESPACE,
                filepath=cr_yaml_path,
            ),
            RayServiceDeleteCREvent(cr, [], 90, NAMESPACE, cr_yaml_path),
        ]

        for cr_event in cr_events:
            cr_event.trigger()

if __name__ == "__main__":
    sys.exit(pytest.main(["-v", "-s", __file__]))
