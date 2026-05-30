#!/usr/bin/env bash
# Provision a local Kind cluster for runwhere-ai E2E tests.
# Constitution §IX (integration-first) + tasks T168.
set -euo pipefail

CLUSTER_NAME="${RWAI_KIND_CLUSTER:-runwhere-ai-dev}"

if ! command -v kind >/dev/null 2>&1; then
  echo "ERROR: kind is not installed. See https://kind.sigs.k8s.io/" >&2
  echo "  macOS:  brew install kind" >&2
  echo "  Linux:  go install sigs.k8s.io/kind@latest" >&2
  exit 1
fi

if kind get clusters | grep -qx "${CLUSTER_NAME}"; then
  echo "✓ Kind cluster '${CLUSTER_NAME}' already exists."
else
  echo "Creating Kind cluster '${CLUSTER_NAME}'…"
  kind create cluster --name "${CLUSTER_NAME}" --wait 60s
fi

kubectl cluster-info --context "kind-${CLUSTER_NAME}"
echo
echo "✓ Cluster ready. To use it: export KUBECONFIG=$(kind get kubeconfig-path --name=${CLUSTER_NAME} 2>/dev/null || echo "~/.kube/config")"
