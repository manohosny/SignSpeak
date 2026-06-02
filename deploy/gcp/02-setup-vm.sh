#!/usr/bin/env bash
# Run ON the VM (after `gcloud compute ssh signspeak`).
# Installs the NVIDIA driver, Docker, and the NVIDIA Container Toolkit so
# Docker containers can use the L4 GPU, then creates the Traefik network.
set -euo pipefail

echo ">> Installing NVIDIA driver (GCP helper)..."
sudo apt-get update -y
# GCP provides a driver installer that picks the right version for the L4.
curl -fsSL https://raw.githubusercontent.com/GoogleCloudPlatform/compute-gpu-installation/main/linux/install_gpu_driver.py -o /tmp/install_gpu_driver.py
sudo python3 /tmp/install_gpu_driver.py
nvidia-smi   # should list the NVIDIA L4

echo ">> Installing Docker Engine + compose plugin..."
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"

echo ">> Installing NVIDIA Container Toolkit..."
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update -y
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker

echo ">> Creating external Traefik network (idempotent)..."
sudo docker network create traefik-public 2>/dev/null || true

echo ""
echo ">> Verifying GPU is visible inside Docker..."
sudo docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi

echo ""
echo "GPU + Docker ready. Log out and back in so the docker group applies,"
echo "then clone the repo and continue with the README (Traefik + stage models + up)."
