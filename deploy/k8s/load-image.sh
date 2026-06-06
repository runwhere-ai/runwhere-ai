#!/usr/bin/env bash
# 把本地 docker 构建好的 runwhere-ai 镜像导入 k3s 的 containerd。
#
# k3s 使用独立于 docker 的 containerd 镜像库，因此需要 save + import，
# 并以 imagePullPolicy: Never 在集群内使用（见 runwhere-ai.yaml）。
#
# 用法（在 runwhere-ai/ 目录）：
#   docker compose build            # 或 docker build -f Dockerfile -t runwhere-ai:latest ..
#   ./deploy/k8s/load-image.sh
set -euo pipefail

SRC_IMAGE="${SRC_IMAGE:-runwhere-ai:latest}"
DST_IMAGE="${DST_IMAGE:-runwhere/ai:dev}"
TAR="${TAR:-/tmp/runwhere-ai-image.tar}"

echo "→ 重打标签 ${SRC_IMAGE} → ${DST_IMAGE}"
docker tag "${SRC_IMAGE}" "${DST_IMAGE}"

echo "→ 导出镜像到 ${TAR}"
docker save "${DST_IMAGE}" -o "${TAR}"

echo "→ 导入 k3s containerd"
sudo k3s ctr images import "${TAR}"

echo "→ 校验"
sudo k3s ctr images ls | grep "${DST_IMAGE}" || { echo "导入后未找到镜像"; exit 1; }
rm -f "${TAR}"
echo "✓ 完成：${DST_IMAGE} 已在 k3s 镜像库"
